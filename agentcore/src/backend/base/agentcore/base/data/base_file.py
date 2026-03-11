import ast
import json
import shutil
import tarfile
from abc import ABC, abstractmethod
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING
from zipfile import ZipFile, is_zipfile

import pandas as pd
from loguru import logger
from agentcore.custom.custom_node.node import Node
from agentcore.io import BoolInput, FileInput, HandleInput, Output, StrInput
from agentcore.schema.data import Data
from agentcore.schema.dataframe import DataFrame
from agentcore.schema.message import Message

if TYPE_CHECKING:
    from collections.abc import Callable


class BaseFileNode(Node, ABC):
    """Base class for handling file processing components.

    This class provides common functionality for resolving, validating, and
    processing file paths. Child classes must define valid file extensions
    and implement the `process_files` method.
    """

    class BaseFile:
        """Internal class to represent a file with additional metadata."""

        def __init__(
            self,
            data: Data | list[Data],
            path: Path,
            *,
            delete_after_processing: bool = False,
            silent_errors: bool = False,
        ):
            self._data = data if isinstance(data, list) else [data]
            self.path = path
            self.delete_after_processing = delete_after_processing
            self._silent_errors = silent_errors

        @property
        def data(self) -> list[Data]:
            return self._data or []

        @data.setter
        def data(self, value: Data | list[Data]):
            if isinstance(value, Data):
                self._data = [value]
            elif isinstance(value, list) and all(isinstance(item, Data) for item in value):
                self._data = value
            else:
                msg = f"data must be a Data object or a list of Data objects. Got: {type(value)}"
                if not self._silent_errors:
                    raise ValueError(msg)

        def merge_data(self, new_data: Data | list[Data] | None) -> list[Data]:
            r"""Generate a new list of Data objects by merging `new_data` into the current `data`.

            Args:
                new_data (Data | list[Data] | None): The new Data object(s) to merge into each existing Data object.
                    If None, the current `data` is returned unchanged.

            Returns:
                list[Data]: A new list of Data objects with `new_data` merged.
            """
            if new_data is None:
                return self.data

            if isinstance(new_data, Data):
                new_data_list = [new_data]
            elif isinstance(new_data, list) and all(isinstance(item, Data) for item in new_data):
                new_data_list = new_data
            else:
                msg = "new_data must be a Data object, a list of Data objects, or None."
                if not self._silent_errors:
                    raise ValueError(msg)
                return self.data

            return [
                Data(data={**data.data, **new_data_item.data}) for data in self.data for new_data_item in new_data_list
            ]

        def __str__(self):
            if len(self.data) == 0:
                text_preview = ""
            elif len(self.data) == 1:
                max_text_length = 50
                text_preview = self.data.get_text()[:max_text_length]
                if len(self.data.get_text()) > max_text_length:
                    text_preview += "..."
                text_preview = f"text_preview='{text_preview}'"
            else:
                text_preview = f"{len(self.data)} data objects"
            return f"BaseFile(path={self.path}, delete_after_processing={self.delete_after_processing}, {text_preview}"

    # Subclasses can override these class variables
    VALID_EXTENSIONS: list[str] = []  # To be overridden by child classes
    IGNORE_STARTS_WITH = [".", "__MACOSX"]

    SERVER_FILE_PATH_FIELDNAME = "file_path"
    SUPPORTED_BUNDLE_EXTENSIONS = ["zip", "tar", "tgz", "bz2", "gz"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._temp_dirs: list[TemporaryDirectory] = []
        # Dynamically update FileInput to include valid extensions and bundles
        self._base_inputs[0].file_types = [
            *self.valid_extensions,
            *self.SUPPORTED_BUNDLE_EXTENSIONS,
        ]

        file_types = ", ".join(self.valid_extensions)
        bundles = ", ".join(self.SUPPORTED_BUNDLE_EXTENSIONS)
        self._base_inputs[
            0
        ].info = f"Supported file extensions: {file_types}; optionally bundled in file extensions: {bundles}"

    _base_inputs = [
        FileInput(
            name="path",
            display_name="Files",
            fileTypes=[],  # Dynamically set in __init__
            info="",  # Dynamically set in __init__
            required=False,
            list=True,
            value=[],
        ),
        HandleInput(
            name="file_path",
            display_name="Server File Path",
            info=(
                f"Data object with a '{SERVER_FILE_PATH_FIELDNAME}' property pointing to server file"
                " or a Message object with a path to the file. Supercedes 'Path' but supports same file types."
            ),
            required=False,
            input_types=["Data", "Message"],
            is_list=True,
            advanced=True,
        ),
        StrInput(
            name="separator",
            display_name="Separator",
            value="\n\n",
            show=True,
            info="Specify the separator to use between multiple outputs in Message format.",
            advanced=True,
        ),
        BoolInput(
            name="silent_errors",
            display_name="Silent Errors",
            advanced=True,
            info="If true, errors will not raise an exception.",
        ),
        BoolInput(
            name="delete_server_file_after_processing",
            display_name="Delete Server File After Processing",
            advanced=True,
            value=True,
            info="If true, the Server File Path will be deleted after processing.",
        ),
        BoolInput(
            name="ignore_unsupported_extensions",
            display_name="Ignore Unsupported Extensions",
            advanced=True,
            value=True,
            info="If true, files with unsupported extensions will not be processed.",
        ),
        BoolInput(
            name="ignore_unspecified_files",
            display_name="Ignore Unspecified Files",
            advanced=True,
            value=False,
            info=f"If true, Data with no '{SERVER_FILE_PATH_FIELDNAME}' property will be ignored.",
        ),
    ]

    _base_outputs = [
        Output(display_name="Files", name="dataframe", method="load_files"),
    ]

    @abstractmethod
    def process_files(self, file_list: list[BaseFile]) -> list[BaseFile]:
        """Processes a list of files.

        Args:
            file_list (list[BaseFile]): A list of file objects.

        Returns:
            list[BaseFile]: A list of BaseFile objects with updated `data`.
        """

    def _cleanup_temp_dirs(self):
        """Clean up all temporary directories created for remote storage downloads."""
        for temp_dir in self._temp_dirs:
            try:
                temp_dir.cleanup()
            except Exception:
                pass
        self._temp_dirs = []

    def __del__(self):
        self._cleanup_temp_dirs()

    def load_files_base(self) -> list[Data]:
        """Loads and parses file(s), including unpacked file bundles.

        Returns:
            list[Data]: Parsed data from the processed files.
        """
        final_files = []  # Initialize to avoid UnboundLocalError
        try:
            # Step 1: Validate the provided paths
            files = self._validate_and_resolve_paths()

            # Step 2: Handle bundles recursively
            all_files = self._unpack_and_collect_files(files)

            # Step 3: Final validation of file types
            final_files = self._filter_and_mark_files(all_files)

            # Step 4: Process files
            processed_files = self.process_files(final_files)

            # Extract and flatten Data objects to return
            return [data for file in processed_files for data in file.data if file.data]

        finally:
            self._cleanup_temp_dirs()

            # Delete files marked for deletion
            for file in final_files:
                if file.delete_after_processing and file.path.exists():
                    if file.path.is_dir():
                        shutil.rmtree(file.path)
                    else:
                        file.path.unlink()

    def load_files_core(self) -> list[Data]:
        """Load files and return as Data objects.

        Returns:
            list[Data]: List of Data objects from all files
        """
        data_list = self.load_files_base()
        if not data_list:
            return [Data()]
        return data_list

    def load_files_message(self) -> Message:
        """Load files and return as Message.

        Returns:
            Message: Message containing all file data
        """
        data_list = self.load_files_core()
        if not data_list:
            return Message()  # No data -> empty message

        sep: str = getattr(self, "separator", "\n\n") or "\n\n"

        parts: list[str] = []
        for d in data_list:
            # Prefer explicit text if available, fall back to full dict, lastly str()
            text = (getattr(d, "get_text", lambda: None)() or d.data.get("text")) if isinstance(d.data, dict) else None
            parts.append(text if text is not None else str(d))

        return Message(text=sep.join(parts))

    def load_files_path(self) -> Message:
        """Returns a Message containing file paths from loaded files.

        Returns:
            Message: Message containing file paths
        """
        files = self._validate_and_resolve_paths()
        paths = [file.path.as_posix() for file in files]

        return Message(text="\n".join(paths) if paths else "")

    def load_files_structured_helper(self, file_path: str) -> list[dict] | None:
        if not file_path:
            return None

        # Map file extensions to pandas read functions with type annotation
        file_readers: dict[str, Callable[[str], pd.DataFrame]] = {
            ".csv": pd.read_csv,
            ".xlsx": pd.read_excel,
            ".parquet": pd.read_parquet,
        }

        # Get file extension in lowercase
        ext = Path(file_path).suffix.lower()

        # Get the appropriate reader function or None
        reader = file_readers.get(ext)

        if reader:
            result = reader(file_path)  # MyPy now knows reader is callable
            return result.to_dict("records")

        return None

    def load_files_structured(self) -> DataFrame:
        """Load files and return as DataFrame with structured content.

        Returns:
            DataFrame: DataFrame containing structured content from all files
        """
        data_list = self.load_files_core()
        if not data_list:
            return DataFrame()

        # Get the file path from the first Data object
        file_path = data_list[0].data.get(self.SERVER_FILE_PATH_FIELDNAME, None)

        # If file_path is provided and is a CSV, read it directly
        if file_path and str(file_path).lower().endswith((".csv", ".xlsx", ".parquet")):
            rows = self.load_files_structured_helper(file_path)
        else:
            # Convert Data objects to a list of dictionaries
            rows = [data_list[0].data]

        self.status = DataFrame(rows)

        return DataFrame(rows)

    def parse_string_to_dict(self, s: str) -> dict:
        # Try JSON first (handles true/false/null)
        try:
            result = json.loads(s)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        # Fall back to Python literal evaluation
        try:
            result = ast.literal_eval(s)
            if isinstance(result, dict):
                return result
        except (SyntaxError, ValueError):
            pass

        # If all parsing fails, return the fallback
        return {"value": s}

    def load_files_json(self) -> Data:
        """Load files and return as a single Data object containing JSON content.

        Returns:
            Data: Data object containing JSON content from all files
        """
        data_list = self.load_files_core()
        if not data_list:
            return Data()

        # Grab the JSON data
        json_data = data_list[0].data[data_list[0].text_key]
        json_data = self.parse_string_to_dict(json_data)

        self.status = Data(data=json_data)

        return Data(data=json_data)

    def load_files(self) -> DataFrame:
        """Load files and return as DataFrame.

        Returns:
            DataFrame: DataFrame containing all file data
        """
        data_list = self.load_files_core()
        if not data_list:
            return DataFrame()

        # Convert Data objects to a list of dictionaries
        all_rows = []
        for data in data_list:
            file_path = data.data.get(self.SERVER_FILE_PATH_FIELDNAME)
            row = dict(data.data) if data.data else {}

            # Add text if available, otherwise use the data's text property
            if "text" in data.data:
                row["text"] = data.data["text"]
            if file_path:
                row["file_path"] = file_path
            all_rows.append(row)

        self.status = DataFrame(all_rows)

        return DataFrame(all_rows)

    @property
    def valid_extensions(self) -> list[str]:
        """Returns valid file extensions for the class.

        This property can be overridden by child classes to provide specific
        extensions.

        Returns:
            list[str]: A list of valid file extensions without the leading dot.
        """
        return self.VALID_EXTENSIONS

    @property
    def ignore_starts_with(self) -> list[str]:
        """Returns prefixes to ignore when unpacking file bundles.

        Returns:
            list[str]: A list of prefixes to ignore when unpacking file bundles.
        """
        return self.IGNORE_STARTS_WITH

    def rollup_data(
        self,
        base_files: list[BaseFile],
        data_list: list[Data | None],
        path_field: str = SERVER_FILE_PATH_FIELDNAME,
    ) -> list[BaseFile]:
        r"""Rolls up Data objects into corresponding BaseFile objects in order given by `base_files`.

        Args:
            base_files (list[BaseFile]): The original BaseFile objects.
            data_list (list[Data | None]): The list of data to be aggregated into the BaseFile objects.
            path_field (str): The field name on the data_list objects that holds the file path as a string.

        Returns:
            list[BaseFile]: A new list of BaseFile objects with merged `data` attributes.
        """

        def _build_data_dict(data_list: list[Data | None], data_list_field: str) -> dict[str, list[Data]]:
            """Builds a dictionary grouping Data objects by a specified field."""
            data_dict: dict[str, list[Data]] = {}
            for data in data_list:
                if data is None:
                    continue
                key = data.data.get(data_list_field)
                if key is None:
                    msg = f"Data object missing required field '{data_list_field}': {data}"
                    self.log(msg)
                    if not self.silent_errors:
                        msg = f"Data object missing required field '{data_list_field}': {data}"
                        self.log(msg)
                        raise ValueError(msg)
                    continue
                data_dict.setdefault(key, []).append(data)
            return data_dict

        # Build the data dictionary from the provided data_list
        data_dict = _build_data_dict(data_list, path_field)

        # Generate the updated list of BaseFile objects, preserving the order of base_files
        updated_base_files = []
        for base_file in base_files:
            new_data_list = data_dict.get(str(base_file.path), [])
            merged_data_list = base_file.merge_data(new_data_list)
            updated_base_files.append(
                BaseFileNode.BaseFile(
                    data=merged_data_list,
                    path=base_file.path,
                    delete_after_processing=base_file.delete_after_processing,
                )
            )

        return updated_base_files

    def _file_path_as_list(self) -> list[Data]:
        file_path = self.file_path
        if not file_path:
            return []

        def _message_to_data(message: Message) -> Data:
            return Data(**{self.SERVER_FILE_PATH_FIELDNAME: message.text})

        if isinstance(file_path, Data):
            file_path = [file_path]
        elif isinstance(file_path, Message):
            file_path = [_message_to_data(file_path)]
        elif not isinstance(file_path, list):
            msg = f"Expected list of Data objects in file_path but got {type(file_path)}."
            self.log(msg)
            if not self.silent_errors:
                raise ValueError(msg)
            return []

        file_paths = []
        for obj in file_path:
            data_obj = _message_to_data(obj) if isinstance(obj, Message) else obj

            if not isinstance(data_obj, Data):
                msg = f"Expected Data object in file_path but got {type(data_obj)}."
                self.log(msg)
                if not self.silent_errors:
                    raise ValueError(msg)
                continue
            file_paths.append(data_obj)

        return file_paths

    def _is_remote_storage(self) -> bool:
        """Check if the current storage backend is remote (non-local) by reading env directly."""
        import os
        storage_type = os.environ.get("STORAGE_TYPE", "local").strip().strip("'\"").lower()
        return storage_type != "local"

    def _resolve_via_storage(self, path_str: str) -> Path:
        """Resolve a storage-relative path to a local filesystem path.

        For local storage: uses the storage service to build the real filesystem path.
        For remote storage (Azure): downloads the file to a temp directory
        so downstream processors can read it via Path.
        """
        import os

        # Must contain a "/" to be a storage-relative path (agent_id/file_name)
        if "/" not in path_str:
            return Path(self.resolve_path(path_str))

        storage_type = os.environ.get("STORAGE_TYPE", "local").strip().strip("'\"").lower()
        logger.info(f"[BaseFile] _resolve_via_storage: path='{path_str}', STORAGE_TYPE='{storage_type}'")

        if storage_type == "azure":
            return self._download_from_azure(path_str)

        # Local storage — use the storage service to build the full path
        try:
            from agentcore.services.deps import get_storage_service
            storage_svc = get_storage_service()
            agent_id, file_name = path_str.split("/", 1)
            full_path = storage_svc.build_full_path(agent_id, file_name)
            return Path(full_path)
        except Exception as e:
            logger.warning(f"[BaseFile] Local storage lookup failed: {e}")
            return Path(self.resolve_path(path_str))

    def _download_from_azure(self, blob_path: str) -> Path:
        """Download a file from Azure Blob Storage to a local temp directory.

        Args:
            blob_path: The full blob path, e.g. 'agent-id/subfolder/file.pdf'

        Returns:
            Path to the downloaded local file.
        """
        import os

        conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
        # Strip any surrounding quotes that dotenv might have kept
        conn_str = conn_str.strip().strip("'\"")
        container_name = os.environ.get("AZURE_STORAGE_CONTAINER_NAME", "agentcore-knowledge-container")
        container_name = container_name.strip().strip("'\"")

        logger.info(
            f"[BaseFile] Azure download: blob='{blob_path}', container='{container_name}', "
            f"conn_str_len={len(conn_str)}, conn_str_start='{conn_str[:40]}...'"
        )

        if not conn_str:
            raise FileNotFoundError(
                f"AZURE_STORAGE_CONNECTION_STRING is empty — cannot download '{blob_path}'"
            )

        from azure.storage.blob import BlobServiceClient

        sync_client = BlobServiceClient.from_connection_string(conn_str)
        try:
            blob_client = sync_client.get_container_client(container_name).get_blob_client(blob_path)
            logger.info(f"[BaseFile] Downloading blob '{blob_path}' from container '{container_name}'...")
            downloader = blob_client.download_blob()
            file_bytes = downloader.readall()
            logger.info(f"[BaseFile] Downloaded {len(file_bytes)} bytes for '{blob_path}'")
        except Exception as e:
            logger.error(f"[BaseFile] Azure blob download FAILED for '{blob_path}': {type(e).__name__}: {e}")
            raise
        finally:
            sync_client.close()

        # Write to temp dir (tracked in self._temp_dirs for cleanup)
        temp_dir = TemporaryDirectory()
        if not hasattr(self, "_temp_dirs"):
            self._temp_dirs = []
        self._temp_dirs.append(temp_dir)

        # Use only the filename (last segment) for the temp file
        file_name = Path(blob_path).name
        local_path = Path(temp_dir.name) / file_name
        local_path.write_bytes(file_bytes)
        logger.info(f"[BaseFile] Saved to temp: {local_path} ({local_path.exists()=})")
        return local_path

    def _validate_and_resolve_paths(self) -> list[BaseFile]:
        """Validate that all input paths exist and are valid, and create BaseFile instances.

        Returns:
            list[BaseFile]: A list of valid BaseFile instances.

        Raises:
            ValueError: If any path does not exist.
        """
        resolved_files = []

        def add_file(data: Data, path: str | Path, *, delete_after_processing: bool):
            path_str = str(path)

            try:
                resolved_path = self._resolve_via_storage(path_str)
            except Exception as e:
                logger.warning(
                    f"[BaseFile] Storage lookup failed for '{path_str}': "
                    f"{type(e).__name__}: {e}"
                )
                resolved_path = Path(self.resolve_path(path_str))

            if not resolved_path.exists():
                msg = f"File or directory not found: {path}"
                self.log(msg)
                logger.error(
                    f"[BaseFile] File not found after resolution: "
                    f"original='{path_str}', resolved='{resolved_path}', "
                    f"exists={resolved_path.exists()}"
                )
                if not self.silent_errors:
                    raise ValueError(msg)
            resolved_files.append(
                BaseFileNode.BaseFile(data, resolved_path, delete_after_processing=delete_after_processing)
            )

        file_path = self._file_path_as_list()
        if self.path and not file_path:
            # Wrap self.path into a Data object
            if isinstance(self.path, list):
                for path in self.path:
                    data_obj = Data(data={self.SERVER_FILE_PATH_FIELDNAME: path})
                    add_file(data=data_obj, path=path, delete_after_processing=False)
            else:
                data_obj = Data(data={self.SERVER_FILE_PATH_FIELDNAME: self.path})
                add_file(data=data_obj, path=self.path, delete_after_processing=False)
        elif file_path:
             for obj in file_path:
                server_file_path = obj.data.get(self.SERVER_FILE_PATH_FIELDNAME)
                if server_file_path:
                    add_file(
                        data=obj,
                        path=server_file_path,
                        delete_after_processing=self.delete_server_file_after_processing,
                    )
                elif not self.ignore_unspecified_files:
                    msg = f"Data object missing '{self.SERVER_FILE_PATH_FIELDNAME}' property."
                    self.log(msg)
                    if not self.silent_errors:
                        raise ValueError(msg)
                else:
                    msg = f"Ignoring Data object missing '{self.SERVER_FILE_PATH_FIELDNAME}' property:\n{obj}"
                    self.log(msg)

        return resolved_files

    def _unpack_and_collect_files(self, files: list[BaseFile]) -> list[BaseFile]:
        """Recursively unpack bundles and collect files into BaseFile instances.

        Args:
            files (list[BaseFile]): List of BaseFile instances to process.

        Returns:
            list[BaseFile]: Updated list of BaseFile instances.
        """
        collected_files = []

        for file in files:
            path = file.path
            delete_after_processing = file.delete_after_processing
            data = file.data

            if path.is_dir():
                # Recurse into directories
                collected_files.extend(
                    [
                        BaseFileNode.BaseFile(
                            data,
                            sub_path,
                            delete_after_processing=delete_after_processing,
                        )
                        for sub_path in path.rglob("*")
                        if sub_path.is_file()
                    ]
                )
            elif path.suffix[1:] in self.SUPPORTED_BUNDLE_EXTENSIONS:
                # Unpack supported bundles
                temp_dir = TemporaryDirectory()
                self._temp_dirs.append(temp_dir)
                temp_dir_path = Path(temp_dir.name)
                self._unpack_bundle(path, temp_dir_path)
                subpaths = list(temp_dir_path.iterdir())
                self.log(f"Unpacked bundle {path.name} into {subpaths}")
                collected_files.extend(
                    [
                        BaseFileNode.BaseFile(
                            data,
                            sub_path,
                            delete_after_processing=delete_after_processing,
                        )
                        for sub_path in subpaths
                    ]
                )
            else:
                collected_files.append(file)

        # Recurse again if any directories or bundles are left in the list
        if any(
            file.path.is_dir() or file.path.suffix[1:] in self.SUPPORTED_BUNDLE_EXTENSIONS for file in collected_files
        ):
            return self._unpack_and_collect_files(collected_files)

        return collected_files

    def _unpack_bundle(self, bundle_path: Path, output_dir: Path):
        """Unpack a bundle into a temporary directory.

        Args:
            bundle_path (Path): Path to the bundle.
            output_dir (Path): Directory where files will be extracted.

        Raises:
            ValueError: If the bundle format is unsupported or cannot be read.
        """

        def _safe_extract_zip(bundle: ZipFile, output_dir: Path):
            """Safely extract ZIP files."""
            for member in bundle.namelist():
                member_path = output_dir / member
                # Ensure no path traversal outside `output_dir`
                if not member_path.resolve().is_relative_to(output_dir.resolve()):
                    msg = f"Attempted Path Traversal in ZIP File: {member}"
                    raise ValueError(msg)
                bundle.extract(member, path=output_dir)

        def _safe_extract_tar(bundle: tarfile.TarFile, output_dir: Path):
            """Safely extract TAR files."""
            for member in bundle.getmembers():
                member_path = output_dir / member.name
                # Ensure no path traversal outside `output_dir`
                if not member_path.resolve().is_relative_to(output_dir.resolve()):
                    msg = f"Attempted Path Traversal in TAR File: {member.name}"
                    raise ValueError(msg)
                bundle.extract(member, path=output_dir)

        # Check and extract based on file type
        if is_zipfile(bundle_path):
            with ZipFile(bundle_path, "r") as zip_bundle:
                _safe_extract_zip(zip_bundle, output_dir)
        elif tarfile.is_tarfile(bundle_path):
            with tarfile.open(bundle_path, "r:*") as tar_bundle:
                _safe_extract_tar(tar_bundle, output_dir)
        else:
            msg = f"Unsupported bundle format: {bundle_path.suffix}"
            raise ValueError(msg)

    def _filter_and_mark_files(self, files: list[BaseFile]) -> list[BaseFile]:
        """Validate file types and mark files for removal.

        Args:
            files (list[BaseFile]): List of BaseFile instances.

        Returns:
            list[BaseFile]: Validated BaseFile instances.

        Raises:
            ValueError: If unsupported files are encountered and `ignore_unsupported_extensions` is False.
        """
        final_files = []
        ignored_files = []

        for file in files:
            if not file.path.is_file():
                self.log(f"Not a file: {file.path.name}")
                continue

            if file.path.suffix[1:].lower() not in self.valid_extensions:
                if self.ignore_unsupported_extensions:
                    ignored_files.append(file.path.name)
                    continue
                msg = f"Unsupported file extension: {file.path.suffix}"
                self.log(msg)
                if not self.silent_errors:
                    raise ValueError(msg)

            final_files.append(file)

        if ignored_files:
            self.log(f"Ignored files: {ignored_files}")

        return final_files
