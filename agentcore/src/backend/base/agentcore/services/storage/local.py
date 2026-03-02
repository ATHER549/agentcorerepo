import anyio
from aiofile import async_open
from loguru import logger

from .service import StorageService


class LocalStorageService(StorageService):
    """A service class for handling local storage operations without aiofiles."""

    def __init__(self, session_service, settings_service) -> None:
        """Initialize the local storage service with session and settings services."""
        super().__init__(session_service, settings_service)
        self.set_ready()

    def build_full_path(self, agent_id: str, file_name: str) -> str:
        """Build the full path of a file in the local storage."""
        return str(self.data_dir / agent_id / file_name)

    async def save_file(self, agent_id: str, file_name: str, data: bytes) -> None:
        """Save a file in the local storage.

        Args:
            agent_id: The identifier for the agent.
            file_name: The name of the file to be saved.
            data: The byte content of the file.

        Raises:
            FileNotFoundError: If the specified agent does not exist.
            IsADirectoryError: If the file name is a directory.
            PermissionError: If there is no permission to write the file.
        """
        folder_path = self.data_dir / agent_id
        await folder_path.mkdir(parents=True, exist_ok=True)
        file_path = folder_path / file_name
        await file_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            async with async_open(str(file_path), "wb") as f:
                await f.write(data)
            logger.info(f"File {file_name} saved successfully in agent {agent_id}.")
        except Exception:
            logger.exception(f"Error saving file {file_name} in agent {agent_id}")
            raise

    async def get_file(self, agent_id: str, file_name: str) -> bytes:
        """Retrieve a file from the local storage.

        Args:
            agent_id: The identifier for the agent.
            file_name: The name of the file to be retrieved.

        Returns:
            The byte content of the file.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        file_path = self.data_dir / agent_id / file_name
        if not await file_path.exists():
            logger.warning(f"File {file_name} not found in agent {agent_id}.")
            msg = f"File {file_name} not found in agent {agent_id}"
            raise FileNotFoundError(msg)

        async with async_open(str(file_path), "rb") as f:
            content = await f.read()

        logger.debug(f"File {file_name} retrieved successfully from agent {agent_id}.")
        return content

    async def list_files(self, agent_id: str):
        """List all files in a specified agent.

        Args:
            agent_id: The identifier for the agent.

        Returns:
            A list of file names.

        Raises:
            FileNotFoundError: If the agent directory does not exist.
        """
        if not isinstance(agent_id, str):
            agent_id = str(agent_id)
        folder_path = self.data_dir / agent_id
        if not await folder_path.exists() or not await folder_path.is_dir():
            logger.warning(f"Agent {agent_id} directory does not exist.")
            msg = f"Agent {agent_id} directory does not exist."
            raise FileNotFoundError(msg)

        files = [
            file.name
            async for file in await anyio.to_thread.run_sync(folder_path.iterdir)
            if await anyio.Path(file).is_file()
        ]

        logger.info(f"Listed {len(files)} files in agent {agent_id}.")
        return files

    async def delete_file(self, agent_id: str, file_name: str) -> None:
        """Delete a file from the local storage.

        :param agent_id: The identifier for the agent.
        :param file_name: The name of the file to be deleted.
        """
        file_path = self.data_dir / agent_id / file_name
        if await file_path.exists():
            await file_path.unlink()
            logger.info(f"File {file_name} deleted successfully from agent {agent_id}.")
        else:
            logger.warning(f"Attempted to delete non-existent file {file_name} in agent {agent_id}.")

    async def teardown(self) -> None:
        """Perform any cleanup operations when the service is being torn down."""
        # No specific teardown actions required for local

    async def get_file_size(self, agent_id: str, file_name: str):
        """Get the size of a file in the local storage."""
        # Get the file size from the file path
        file_path = self.data_dir / agent_id / file_name
        if not await file_path.exists():
            logger.warning(f"File {file_name} not found in agent {agent_id}.")
            msg = f"File {file_name} not found in agent {agent_id}"
            raise FileNotFoundError(msg)

        file_size_stat = await file_path.stat()
        return file_size_stat.st_size
