from asyncio import create_subprocess_exec
from asyncio.subprocess import PIPE
from configparser import ConfigParser
from random import SystemRandom
from os import path as ospath, remove as osremove, walk
from string import ascii_letters, digits
from bot import GLOBAL_EXTENSION_FILTER, LOGGER, status_dict, status_dict_lock, remotes_data, config_dict
from bot.helper.ext_utils.bot_utils import run_sync
from bot.helper.ext_utils.filters import CustomFilters
from bot.helper.ext_utils.human_format import get_readable_file_size
from bot.helper.ext_utils.message_utils import sendStatusMessage
from bot.helper.ext_utils.misc_utils import clean_download
from bot.helper.ext_utils.rclone_data_holder import get_rclone_data
from bot.helper.ext_utils.rclone_utils import get_rclone_config
from bot.helper.mirror_leech_utils.status_utils.rclone_status import RcloneStatus
from bot.helper.mirror_leech_utils.status_utils.status_utils import MirrorStatus



class RcloneMirror:
    def __init__(self, path, name, size, user_id, listener):
        self.__path = path
        self.__listener = listener
        self.__user_id= user_id
        self.name= name
        self.size= size
        self.process= None
        self.__isGdrive= False
        self.status_type = MirrorStatus.STATUS_UPLOADING

    async def mirror(self):
        await self.delete_files_with_extensions()
       
        if self.__listener.extract:
            mime_type = 'Folder'
        else:
            mime_type = 'File'

        config_file = get_rclone_config(self.__user_id)
        conf = ConfigParser()
        conf.read(config_file)

        is_multi_remote_up = config_dict['MULTI_REMOTE_UP']
        is_owner_query = CustomFilters._owner_query(self.__user_id)

        if config_dict['MULTI_RCLONE_CONFIG'] or is_owner_query:
            if is_multi_remote_up:
                if len(remotes_data) > 0:
                    for remote in remotes_data:
                        for r in conf.sections():

                            if remote == str(r):
                                if conf[r]['type'] == 'drive':
                                    self.__isGdrive = True
                                    break

                        if mime_type == 'Folder':
                            self.name = self.name.replace(".", "")
                            cmd = ['rclone', 'copy', f"--config={config_file}", str(self.__path), f"{remote}:/{self.name}", '-P']
                        else:
                            cmd = ['rclone', 'copy', f"--config={config_file}", str(self.__path), f"{remote}:", '-P']
                        await self.upload(cmd, config_file, mime_type, remote)
                await clean_download(self.__path)
            else:
                remote = get_rclone_data('CLOUDSEL_REMOTE', self.__user_id)
                base = get_rclone_data('CLOUDSEL_BASE_DIR', self.__user_id)
                
                for r in conf.sections():
                    if remote == str(r):
                        if conf[r]['type'] == 'drive':
                            self.__isGdrive = True
                            break

                if mime_type == 'Folder':
                    self.name = self.name.replace(".", "")
                    cmd = ['rclone', 'copy', f"--config={config_file}", str(self.__path), f"{remote}:/{self.name}", '-P']
                else:
                    cmd = ['rclone', 'copy', f"--config={config_file}", str(self.__path), f"{remote}:", '-P']
                await self.upload(cmd, config_file, mime_type, remote, base)
        else:
            if DEFAULT_GLOBAL_REMOTE := config_dict['DEFAULT_GLOBAL_REMOTE']:
                remote= DEFAULT_GLOBAL_REMOTE

                for r in conf.sections():
                    if remote == str(r):
                        if conf[r]['type'] == 'drive':
                            self.__isGdrive = True
                            break

                if mime_type == 'Folder':
                    self.name = self.name.replace(".", "")
                    cmd = ['rclone', 'copy', f"--config={config_file}", str(self.__path), f"{remote}:/{self.name}", '-P']
                else:
                    cmd = ['rclone', 'copy', f"--config={config_file}", str(self.__path), f"{remote}:", '-P']
                await self.upload(cmd, config_file, mime_type, remote)
            else:
                return await self.__listener.onUploadError("DEFAULT_GLOBAL_REMOTE not found")
        
    async def upload(self, cmd, config_file, mime_type, remote, base="/"):
        gid = ''.join(SystemRandom().choices(ascii_letters + digits, k=10))
        async with status_dict_lock:
            status = RcloneStatus(self, gid)
            status_dict[self.__listener.uid] = status
        await sendStatusMessage(self.__listener.message)
        self.process = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
        await status.read_stdout()
        return_code = await self.process.wait()
        if return_code == 0:
            size = get_readable_file_size(self.size)
            await self.__listener.onRcloneUploadComplete(self.name, size, config_file, remote, base, mime_type, self.__isGdrive)
        else:
            error= await self.process.stderr.read()
            LOGGER.info(str(error))
            await self.__listener.onUploadError("Cancelled by user")

    async def delete_files_with_extensions(self):
        for dirpath, _, files in walk(self.__path):
            for file in files:
                if file.lower().endswith(tuple(GLOBAL_EXTENSION_FILTER)):
                    try:
                        del_file = ospath.join(dirpath, file)
                        osremove(del_file)
                    except:
                        return

    async def cancel_download(self):
        await run_sync(self.process.kill)
        