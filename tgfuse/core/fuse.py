import os, stat, errno, asyncio, time, contextlib

from tgfuse.funcs.channel import gather_all_docs

import pyfuse3
import pyfuse3.asyncio
pyfuse3.asyncio.enable()

from pyfuse3 import FUSEError, ROOT_INODE, FileInfo, EntryAttributes
from typing import Sequence, Tuple

from tgfuse.config import logging_config
log = logging_config.setup_logging(__name__)

class TelegramFS(pyfuse3.Operations):
    def __init__(self, client, chat_id: int, read_only: bool, cache_enabled: bool):
        super().__init__()
        self._tg_client = client
        self._chat_id = chat_id
        self.read_only = read_only

        self.enable_writeback_cache = False
        self.supports_dot_lookup = False

        self._root_inode = ROOT_INODE
        self._next_inode = 2
        self._cache_enabled = cache_enabled

        # name -> inode
        self._name_to_inode = {}
        # message_id -> inode
        self._msg_id_to_inode = {}

        # inode -> {
        #   'message_id': int or None,
        #   'file_id': str or None,
        #   'file_name': bytes,
        #   'size': int,
        #   'timestamp': int,
        #   'data': bytearray,
        #   'dirty': bool,
        #   'refcount': int
        # }
        self._files = {}

        # For delayed uploads of new files => { inode: asyncio.Task }
        self._delayed_upload_tasks = {}
        # For channel sync
        self._sync_task = None

        # fh -> inode
        self._fh_to_inode = {}
        self._next_fh = 1

    async def init_fs(self):
        """Gather initial docs, then start periodic sync."""
        await self._sync_initial_docs()
        self._sync_task = asyncio.create_task(self._periodic_sync_task())

    async def destroy(self):
        """Called on unmount => stop background tasks."""
        if self._sync_task:
            self._sync_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._sync_task
        log.info("destroy() done - FS unmounted.")

    async def _sync_initial_docs(self):
        log.info("Initial sync: gather existing docs from channel...")
        docs = await gather_all_docs(self._tg_client, self._chat_id)
        for (m_id, f_id, fname_b, size, ts) in docs:
            inode = self._next_inode
            self._next_inode += 1

            unique_fname = self._unique_file_name(fname_b)
            self._files[inode] = {
                'message_id': m_id,
                'file_id': f_id,
                'file_name': unique_fname,
                'size': size,
                'timestamp': ts,
                'data': bytearray(),
                'dirty': False,
                'refcount': 0
            }
            self._name_to_inode[unique_fname] = inode
            self._msg_id_to_inode[m_id] = inode

        log.info(f"Initial sync done, loaded {len(self._files)} files.")

    async def _periodic_sync_task(self):
        """Runs every 30s, checks for new/removed docs in the channel."""
        while True:
            try:
                await asyncio.sleep(30)
                await self._sync_channel_updates()
            except asyncio.CancelledError:
                log.info("Background sync task cancelled.")
                return
            except Exception as e:
                log.exception(f"Periodic sync task error: {e}")

    async def _sync_channel_updates(self):
        """Add new docs & remove missing docs from local state."""
        log.debug("Syncing channel updates...")
        docs = await gather_all_docs(self._tg_client, self._chat_id)
        current_msgs = {}
        for (m_id, f_id, fname_b, size, ts) in docs:
            current_msgs[m_id] = (f_id, fname_b, size, ts)

        old_msg_ids = set(self._msg_id_to_inode.keys())
        new_msg_ids = set(current_msgs.keys())

        # removed
        removed = old_msg_ids - new_msg_ids
        for msg_id in removed:
            inode = self._msg_id_to_inode[msg_id]
            info = self._files.get(inode)
            if not info:
                continue
            if info['refcount'] > 0:
                log.debug(f"Skipping removal inode={inode}, msg_id={msg_id} because open.")
                continue
            fname = info['file_name']
            log.info(f"Doc removed => inode={inode} name={fname}.")
            self._files.pop(inode, None)
            self._name_to_inode.pop(fname, None)
            self._msg_id_to_inode.pop(msg_id, None)

        # added
        added = new_msg_ids - old_msg_ids
        for msg_id in added:
            (f_id, fname_b, size, ts) = current_msgs[msg_id]
            inode = self._next_inode
            self._next_inode += 1
            unique_fname = self._unique_file_name(fname_b)
            self._files[inode] = {
                'message_id': msg_id,
                'file_id': f_id,
                'file_name': unique_fname,
                'size': size,
                'timestamp': ts,
                'data': bytearray(),
                'dirty': False,
                'refcount': 0
            }
            self._name_to_inode[unique_fname] = inode
            self._msg_id_to_inode[msg_id] = inode
            log.info(f"New doc => inode={inode}, name={unique_fname}, msg_id={msg_id}")

        log.debug("Channel sync complete.")

    def _unique_file_name(self, fname: bytes) -> bytes:
        """If conflict, append _2, _3, etc."""
        base = fname
        idx = 2
        while fname in self._name_to_inode:
            fname = base + f"_{idx}".encode('utf-8')
            idx += 1
        return fname

    # Read/Write Helpers
    async def _download_if_needed(self, inode: int):
        f = self._files[inode]
        if len(f['data']) == 0 and f['file_id'] is not None and f['size'] > 0:
            log.debug(f"Downloading content inode={inode}, file_id={f['file_id']}")
            bio = await self._tg_client.download_media(f['file_id'], in_memory=True)
            bio.seek(0)
            f['data'] = bytearray(bio.read())
            log.debug(f"Downloaded {len(f['data'])} bytes for inode={inode}.")

    async def _upload_existing_file(self, inode: int):
        f = self._files[inode]
        old_mid = f['message_id']
        if old_mid:
            try:
                await self._tg_client.delete_messages(self._chat_id, old_mid)
            except Exception as e:
                log.warning(f"Deleting old msg_id={old_mid} failed: {e}")

        size = len(f['data'])
        if size == 0:
            log.debug(f"Skipping upload for zero-length inode={inode}.")
            f['dirty'] = False
            f['size'] = 0
            return

        from io import BytesIO
        b = BytesIO(f['data'])
        b.name = f['file_name'].decode('utf-8', 'replace')

        try:
            msg = await self._tg_client.send_document(self._chat_id, document=b)
            f['file_id'] = msg.document.file_id
            f['message_id'] = msg.id
            f['size'] = size
            f['timestamp'] = int(time.time())
            f['dirty'] = False
            self._msg_id_to_inode[msg.id] = inode
            log.debug(f"Re-upload => inode={inode}, msg_id={msg.id}")
        except Exception as e:
            log.error(f"Re-upload failed inode={inode}: {e}")
        finally:
            # If cache is off and file is still closed, clear out the data
            if f['refcount'] == 0 and not self._cache_enabled:
                f['data'].clear()

    async def _delayed_upload_new_file(self, inode: int, delay_s: int = 5):
        log.debug(f"Inode={inode} => new => delay {delay_s}s.")
        await asyncio.sleep(delay_s)

        if inode not in self._files:
            log.debug(f"Inode={inode} unlinked before upload => skip.")
            return

        f = self._files[inode]

        # Possibly the user re-opened or appended. If it’s not dirty or has file_id,
        # we skip uploading:
        if not f['dirty'] or f['file_id'] is not None:
            log.debug(f"Inode={inode} no longer new or not dirty => skip.")
            return

        size = len(f['data'])
        if size == 0:
            log.debug(f"Zero-length inode={inode}, skip upload.")
            return

        from io import BytesIO
        b = BytesIO(f['data'])
        b.name = f['file_name'].decode('utf-8', 'replace')

        try:
            msg = await self._tg_client.send_document(self._chat_id, document=b)
            f['file_id'] = msg.document.file_id
            f['message_id'] = msg.id
            f['size'] = size
            f['timestamp'] = int(time.time())
            f['dirty'] = False
            self._msg_id_to_inode[msg.id] = inode
            log.debug(f"Delayed upload => inode={inode}, msg_id={msg.id}")
        except Exception as e:
            log.error(f"Delayed upload failed inode={inode}: {e}")
        finally:
            # If cache is off and file is still closed, discard data
            if inode in self._files:
                if f['refcount'] == 0 and not self._cache_enabled:
                    f['data'].clear()

            self._delayed_upload_tasks.pop(inode, None)

    # FUSE ops
    async def getattr(self, inode, ctx=None) -> EntryAttributes:
        now_ns = int(time.time() * 1e9)
        if inode == self._root_inode:
            attr = EntryAttributes()
            attr.st_mode = (stat.S_IFDIR | 0o755)
            attr.st_ino = inode
            attr.st_uid = os.getuid()
            attr.st_gid = os.getgid()
            attr.st_size = 0
            attr.st_nlink = 2
            attr.st_atime_ns = now_ns
            attr.st_mtime_ns = now_ns
            attr.st_ctime_ns = now_ns
            attr.entry_timeout = 300
            attr.attr_timeout = 300
            return attr

        f = self._files.get(inode)
        if not f:
            raise FUSEError(errno.ENOENT)

        attr = EntryAttributes()
        attr.st_ino = inode
        if self.read_only:
            attr.st_mode = (stat.S_IFREG | 0o444)  # read-only
        else:
            attr.st_mode = (stat.S_IFREG | 0o644)  # read/write
        attr.st_uid = os.getuid()
        attr.st_gid = os.getgid()
        attr.st_nlink = 1
        attr.st_size = f['size']
        t_ns = f['timestamp'] * 10**9
        attr.st_atime_ns = t_ns
        attr.st_mtime_ns = t_ns
        attr.st_ctime_ns = t_ns
        attr.entry_timeout = 300
        attr.attr_timeout = 300
        return attr

    async def lookup(self, parent_inode, name, ctx=None) -> EntryAttributes:
        if parent_inode != self._root_inode:
            raise FUSEError(errno.ENOENT)
        inode = self._name_to_inode.get(name)
        if not inode:
            raise FUSEError(errno.ENOENT)
        return await self.getattr(inode)

    async def opendir(self, inode, ctx):
        if inode != self._root_inode:
            raise FUSEError(errno.ENOTDIR)
        return inode

    async def readdir(self, fh, start_id, token):
        if fh != self._root_inode:
            raise FUSEError(errno.ENOTDIR)

        for fname, inode in sorted(self._name_to_inode.items(), key=lambda x: x[1]):
            if inode < start_id:
                continue
            attr = await self.getattr(inode)
            next_off = inode + 1
            ok = pyfuse3.readdir_reply(token, fname, attr, next_off)
            if not ok:
                break

    async def create(self, parent_inode, name, mode, flags, ctx):
        if self.read_only:
            raise FUSEError(errno.EROFS)
        if parent_inode != self._root_inode:
            raise FUSEError(errno.EPERM)

        inode = self._next_inode
        self._next_inode += 1
        unique_name = self._unique_file_name(name)

        self._files[inode] = {
            'message_id': None,
            'file_id': None,
            'file_name': unique_name,
            'size': 0,
            'timestamp': int(time.time()),
            'data': bytearray(),
            'dirty': False,
            'refcount': 1
        }
        self._name_to_inode[unique_name] = inode

        fh = self._next_fh
        self._next_fh += 1
        self._fh_to_inode[fh] = inode

        fi = FileInfo(fh=fh)
        attr = await self.getattr(inode)
        return (fi, attr)

    async def open(self, inode, flags, ctx):
        if inode not in self._files:
            raise FUSEError(errno.ENOENT)
        f = self._files[inode]

        # Check write access
        accmode = (flags & os.O_ACCMODE)
        if self.read_only and (accmode == os.O_WRONLY or accmode == os.O_RDWR):
            raise FUSEError(errno.EROFS)

        if not self.read_only and (flags & os.O_TRUNC):
            f['data'].clear()
            f['size'] = 0
            f['dirty'] = False
            f['file_id'] = None
            f['message_id'] = None

        await self._download_if_needed(inode)

        f['refcount'] += 1
        fh = self._next_fh
        self._next_fh += 1
        self._fh_to_inode[fh] = inode
        return FileInfo(fh=fh)

    async def release(self, fh):
        inode = self._fh_to_inode.pop(fh, None)
        if inode is None:
            return

        f = self._files[inode]
        f['refcount'] -= 1
        if f['refcount'] < 0:
            f['refcount'] = 0

        if f['refcount'] == 0:
            # Always update size in case new writes came in
            f['size'] = len(f['data'])

            # 1) If not dirty at all, we can discard immediately (if cache is off).
            if not f['dirty']:
                if not self._cache_enabled:
                    f['data'].clear()
                return

            # 2) If read_only, we cannot upload => clear if cache is off.
            if self.read_only:
                if not self._cache_enabled:
                    f['data'].clear()
                return

            # 3) Not read-only + dirty => needs upload
            if f['file_id'] is None:
                # New file => schedule delayed upload
                old_task = self._delayed_upload_tasks.pop(inode, None)
                if old_task:
                    old_task.cancel()

                t = asyncio.create_task(self._delayed_upload_new_file(inode, 5))
                self._delayed_upload_tasks[inode] = t
            else:
                # Existing file => immediate re-upload
                await self._upload_existing_file(inode)

    async def read(self, fh, offset, size):
        inode = self._fh_to_inode.get(fh)
        if inode is None:
            raise FUSEError(errno.EBADF)
        f = self._files[inode]
        return bytes(f['data'][offset:offset+size])

    async def write(self, fh, offset, data):
        if self.read_only:
            raise FUSEError(errno.EROFS)
        inode = self._fh_to_inode.get(fh)
        if inode is None:
            raise FUSEError(errno.EBADF)
        f = self._files[inode]
        buf = f['data']
        end = offset + len(data)
        if offset > len(buf):
            buf.extend(b"\0"*(offset - len(buf)))
        buf[offset:end] = data
        f['dirty'] = True
        return len(data)

    async def unlink(self, parent_inode, name, ctx):
        if self.read_only:
            raise FUSEError(errno.EROFS)
        if parent_inode != self._root_inode:
            raise FUSEError(errno.ENOTDIR)
        inode = self._name_to_inode.get(name)
        if inode is None:
            raise FUSEError(errno.ENOENT)

        # cancel delayed upload
        t = self._delayed_upload_tasks.pop(inode, None)
        if t:
            t.cancel()

        f = self._files[inode]
        old_mid = f['message_id']
        if old_mid:
            try:
                await self._tg_client.delete_messages(self._chat_id, old_mid)
            except Exception as e:
                log.warning(f"Deleting message {old_mid} failed: {e}")
            self._msg_id_to_inode.pop(old_mid, None)

        self._files.pop(inode, None)
        self._name_to_inode.pop(name, None)

    async def mkdir(self, *args, **kwargs):
        raise FUSEError(errno.ENOTDIR)

    async def rmdir(self, *args, **kwargs):
        raise FUSEError(errno.ENOTDIR)

    async def rename(self, *args, **kwargs):
        raise FUSEError(errno.ENOSYS)

    async def link(self, *args, **kwargs):
        raise FUSEError(errno.ENOSYS)

    async def symlink(self, *args, **kwargs):
        raise FUSEError(errno.ENOSYS)

    async def mknod(self, *args, **kwargs):
        raise FUSEError(errno.ENOSYS)

    async def flush(self, fh: pyfuse3.FileHandleT) -> None:
        return

    async def fsync(self, fh: pyfuse3.FileHandleT, datasync: bool) -> None:
        return

    async def fsyncdir(self, fh: pyfuse3.FileHandleT, datasync: bool) -> None:
        return

    async def releasedir(self, fh: pyfuse3.FileHandleT) -> None:
        return

    async def forget(self, inode_list: Sequence[Tuple[pyfuse3.InodeT, int]]) -> None:
        return

    async def ioctl(self, fh, command, arg, fip, in_buf, out_buf_size) -> bytes:
        raise FUSEError(errno.ENOTTY)

    async def copy_file_range(
        self, fh_in, off_in, fh_out, off_out, length, flags
    ) -> int:
        raise FUSEError(errno.EOPNOTSUPP)

    async def statfs(self, ctx):
        st = pyfuse3.StatvfsData()
        st.f_bsize = 4096
        st.f_frsize = 4096
        st.f_blocks = 1_000_000
        st.f_bfree  = 500_000
        st.f_bavail = 500_000
        st.f_files  = 10_000
        st.f_ffree  = 9_000
        st.f_favail = 9_000
        st.f_namemax = 255
        return st


async def fuse_stopper(fs):
    log.info("Unmounting FUSE...")
    await fs.destroy()
    pyfuse3.close()


async def fuse_runner(mountpoint, fs, fuse_opts):
    try:
        log.info("Initializing pyfuse3...")
        pyfuse3.init(fs, mountpoint, fuse_opts)
        log.info("Starting FUSE main loop...")
        await pyfuse3.main()
    finally:
        await fuse_stopper(fs)

if __name__ == "__main__":
    raise RuntimeError("This module should be run only via main.py")
