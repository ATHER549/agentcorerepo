import { useEffect, useMemo, useState } from "react";
import { ICON_STROKE_WIDTH } from "@/constants/constants";
import { useGetFilesV2 } from "@/controllers/API/queries/file-management";
import { useGetKnowledgeBases } from "@/controllers/API/queries/knowledge-bases/use-get-knowledge-bases";
import { usePostUploadFile } from "@/controllers/API/queries/files/use-post-upload-file";
import { ENABLE_FILE_MANAGEMENT } from "@/customization/feature-flags";
import { createFileUpload } from "@/helpers/create-file-upload";
import BaseModal from "@/modals/baseModal";
import FilesRendererComponent from "@/modals/fileManagerModal/components/filesRendererComponent";
import useFileSizeValidator from "@/shared/hooks/use-file-size-validator";
import { cn } from "@/utils/utils";
import {
  CONSOLE_ERROR_MSG,
  INVALID_FILE_ALERT,
} from "../../../../../constants/alerts_constants";
import useAlertStore from "../../../../../stores/alertStore";
import useAgentsManagerStore from "../../../../../stores/agentsManagerStore";
import IconComponent, {
  ForwardedIconComponent,
} from "../../../../common/genericIconComponent";
import { Button } from "../../../../ui/button";
import { Input } from "../../../../ui/input";
import type { FileComponentType, InputProps } from "../../types";

export default function InputFileComponent({
  value,
  file_path,
  handleOnNewValue,
  disabled,
  fileTypes,
  isList,
  tempFile = true,
  editNode = false,
  id,
}: InputProps<string, FileComponentType>): JSX.Element {
  const currentAgentId = useAgentsManagerStore((state) => state.currentAgentId);
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const { validateFileSize } = useFileSizeValidator();

  // Clear component state
  useEffect(() => {
    if (disabled && value !== "") {
      handleOnNewValue({ value: "", file_path: "" }, { skipSnapshot: true });
    }
  }, [disabled, handleOnNewValue]);

  function checkFileType(fileName: string): boolean {
    if (fileTypes === undefined) return true;

    // Extract the file extension
    const fileExtension = fileName.split(".").pop();

    // Check if the extracted extension is in the list of accepted file types
    return fileTypes.includes(fileExtension || "");
  }

  const { mutateAsync, isPending } = usePostUploadFile();
  const normalizePath = (path: string) =>
    path.replaceAll("\\", "/").toLowerCase();
  const [isKnowledgeBaseModalOpen, setIsKnowledgeBaseModalOpen] =
    useState(false);
  const [selectedKnowledgeBaseIds, setSelectedKnowledgeBaseIds] = useState<
    string[]
  >([]);
  const [expandedSelectedKbIds, setExpandedSelectedKbIds] = useState<
    Record<string, boolean>
  >({});
  const [expandedModalKbIds, setExpandedModalKbIds] = useState<
    Record<string, boolean>
  >({});
  const [knowledgeBaseSearch, setKnowledgeBaseSearch] = useState("");

  const handleButtonClick = (): void => {
    createFileUpload({ multiple: isList, accept: fileTypes?.join(",") }).then(
      (files) => {
        if (files.length === 0) return;

        // For single file mode, only process the first file
        const filesToProcess = isList ? files : [files[0]];

        // Validate all files
        for (const file of filesToProcess) {
          try {
            validateFileSize(file);
          } catch (e) {
            if (e instanceof Error) {
              setErrorData({
                title: e.message,
              });
            }
            return;
          }
          if (!checkFileType(file.name)) {
            setErrorData({
              title: INVALID_FILE_ALERT,
              list: [fileTypes?.join(", ") || ""],
            });
            return;
          }
        }

        // Upload all files
        Promise.all(
          filesToProcess.map(
            (file) =>
              new Promise<{ file_name: string; file_path: string } | null>(
                async (resolve) => {
                  const data = await mutateAsync(
                    { file, id: currentAgentId },
                    {
                      onError: (error) => {
                        console.error(CONSOLE_ERROR_MSG);
                        setErrorData({
                          title: "Error uploading file",
                          list: [error.response?.data?.detail],
                        });
                        resolve(null);
                      },
                    },
                  );
                  resolve({
                    file_name: file.name,
                    file_path: data.file_path,
                  });
                },
              ),
          ),
        )
          .then((results) => {
            console.warn(results);
            // Filter out any failed uploads
            const successfulUploads = results.filter(
              (r): r is { file_name: string; file_path: string } => r !== null,
            );

            if (successfulUploads.length > 0) {
              const fileNames = successfulUploads.map(
                (result) => result.file_name,
              );
              const filePaths = successfulUploads.map(
                (result) => result.file_path,
              );

              // For single file mode, just use the first result
              // For list mode, join with commas
              handleOnNewValue({
                value: isList ? fileNames : fileNames[0],
                file_path: isList ? filePaths : filePaths[0],
              });
            }
          })
          .catch((e) => {
            console.error(e);
            // Error handling is done in the onError callback above
          });
      },
    );
  };

  const isDisabled = disabled || isPending;

  const { data: files } = useGetFilesV2({
    enabled: !!ENABLE_FILE_MANAGEMENT,
  });
  const { data: knowledgeBases } = useGetKnowledgeBases({
    enabled: !!ENABLE_FILE_MANAGEMENT,
  });

  const knowledgeBaseFileGroups = useMemo(() => {
    if (!knowledgeBases || !files) return [];
    return knowledgeBases.map((kb) => ({
      id: kb.id,
      name: kb.name,
      files: files.filter((file) => file.knowledge_base_id === kb.id),
    }));
  }, [knowledgeBases, files]);

  const filteredKnowledgeBaseFileGroups = useMemo(() => {
    const query = knowledgeBaseSearch.trim().toLowerCase();
    if (!query) return knowledgeBaseFileGroups;
    return knowledgeBaseFileGroups.filter((group) => {
      const kbNameMatch = group.name.toLowerCase().includes(query);
      const fileNameMatch = group.files.some((file) =>
        file.name.toLowerCase().includes(query),
      );
      return kbNameMatch || fileNameMatch;
    });
  }, [knowledgeBaseFileGroups, knowledgeBaseSearch]);

  const selectedFiles = (
    isList
      ? Array.isArray(file_path)
        ? file_path.filter((value) => value !== "")
        : typeof file_path === "string"
          ? [file_path]
          : []
      : Array.isArray(file_path)
        ? (file_path ?? [])
        : [file_path ?? ""]
  ).filter((value) => value !== "");

  const selectedKnowledgeBaseGroups = useMemo(() => {
    if (!files || !knowledgeBases) return [];
    const selectedPathSet = new Set(selectedFiles.map(normalizePath));
    const groupedByKb = new Map<
      string,
      { id: string; name: string; files: any[] }
    >();
    files
      .filter((file) => selectedPathSet.has(normalizePath(file.path)))
      .forEach((file) => {
        if (!file.knowledge_base_id) return;
        const kb = knowledgeBases.find((item) => item.id === file.knowledge_base_id);
        if (!kb) return;
        const existing = groupedByKb.get(kb.id);
        if (existing) {
          existing.files.push(file);
        } else {
          groupedByKb.set(kb.id, {
            id: kb.id,
            name: kb.name,
            files: [file],
          });
        }
      });
    return Array.from(groupedByKb.values());
  }, [files, knowledgeBases, selectedFiles]);

  const applyKnowledgeBaseSelection = (kbIds: string[]) => {
    if (!files || !knowledgeBases) return;
    const selectedKbs = knowledgeBases.filter((kb) => kbIds.includes(kb.id));
    const normalizedKbNames = selectedKbs.map((kb) =>
      normalizePath(kb.name),
    );

    // Primary mapping via knowledge_base_id, fallback via storage folder segment in file path.
    const scopedByKbId = files.filter(
      (file) => file.knowledge_base_id && kbIds.includes(file.knowledge_base_id),
    );
    const scopedByPath = files.filter((file) => {
      const normalizedFilePath = normalizePath(file.path);
      return normalizedKbNames.some((kbName) =>
        normalizedFilePath.includes(`/${kbName}/`),
      );
    });

    const dedupedByPath = new Map<string, (typeof files)[number]>();
    [...scopedByKbId, ...scopedByPath].forEach((file) => {
      dedupedByPath.set(normalizePath(file.path), file);
    });
    const scopedFiles = Array.from(dedupedByPath.values());
    const filePaths = scopedFiles.map((file) => file.path);
    handleOnNewValue({
      // Keep value aligned with file_path so backend realtime updates
      // never receive KB display names as file input values.
      value: isList ? filePaths : (filePaths[0] ?? ""),
      file_path: isList ? filePaths : (filePaths[0] ?? ""),
    });
  };

  useEffect(() => {
    if (files !== undefined && !tempFile) {
      const selectedPathSet = new Set(selectedFiles.map(normalizePath));
      const validSelectedFiles = files.filter((f) =>
        selectedPathSet.has(normalizePath(f.path)),
      );
      if (validSelectedFiles.length === selectedFiles.length) return;
      if (selectedFiles.length > 0 && validSelectedFiles.length === 0) return;

      const validPaths = validSelectedFiles.map((f) => f.path);
      handleOnNewValue({
        value: isList ? validPaths : (validPaths[0] ?? ""),
        file_path: isList ? validPaths : (validPaths[0] ?? ""),
      });
    }
  }, [files, file_path, selectedFiles, isList]);

  return (
    <div className="w-full">
      <div className="flex flex-col gap-2.5">
        <div className="flex items-center gap-2.5">
          {ENABLE_FILE_MANAGEMENT && !tempFile ? (
            files && (
              <div className="relative flex w-full flex-col gap-2">
                <div className="nopan nowheel flex max-h-44 flex-col overflow-y-auto">
                  <div className="flex flex-col gap-2">
                    {selectedKnowledgeBaseGroups.map((group) => {
                      const isExpanded = expandedSelectedKbIds[group.id] ?? true;
                      return (
                        <div key={group.id} className="rounded-md border bg-background">
                          <div className="flex items-center justify-between px-3 py-2">
                            <button
                              type="button"
                              className="flex items-center gap-2 text-sm font-semibold"
                              onClick={() =>
                                setExpandedSelectedKbIds((prev) => ({
                                  ...prev,
                                  [group.id]: !isExpanded,
                                }))
                              }
                            >
                              <ForwardedIconComponent
                                name={isExpanded ? "ChevronDown" : "ChevronRight"}
                                className="h-4 w-4"
                              />
                              <ForwardedIconComponent name="Database" className="h-4 w-4" />
                              <span>{group.name}</span>
                              <span className="text-xs text-muted-foreground">
                                ({group.files.length} files)
                              </span>
                            </button>
                            <Button
                              variant="ghost"
                              size="iconMd"
                              onClick={() => {
                                const remainingFiles = selectedFiles.filter(
                                  (path) =>
                                    !group.files.some((groupFile) => groupFile.path === path),
                                );
                                handleOnNewValue({
                                  value: isList
                                    ? remainingFiles
                                    : (remainingFiles[0] ?? ""),
                                  file_path: isList
                                    ? remainingFiles
                                    : (remainingFiles[0] ?? ""),
                                });
                              }}
                            >
                              <ForwardedIconComponent name="X" className="h-4 w-4" />
                            </Button>
                          </div>
                          {isExpanded && (
                            <div className="border-t px-3 py-2">
                              <FilesRendererComponent files={group.files} />
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
                <BaseModal
                  size="small"
                  className="h-[68vh]"
                  open={isKnowledgeBaseModalOpen}
                  setOpen={(open) => {
                    setIsKnowledgeBaseModalOpen(open);
                    if (!open) {
                      setKnowledgeBaseSearch("");
                    }
                  }}
                  onSubmit={() => {
                    applyKnowledgeBaseSelection(selectedKnowledgeBaseIds);
                    setIsKnowledgeBaseModalOpen(false);
                    setKnowledgeBaseSearch("");
                  }}
                >
                  <BaseModal.Header description="Select one or more knowledge bases.">
                    Select Knowledge Base
                  </BaseModal.Header>
                  <BaseModal.Content className="gap-2 overflow-auto">
                    <Input
                      icon="Search"
                      placeholder="Search knowledge bases"
                      value={knowledgeBaseSearch}
                      onChange={(event) =>
                        setKnowledgeBaseSearch(event.target.value)
                      }
                      data-testid="search-knowledge-base-select-input"
                    />
                    {filteredKnowledgeBaseFileGroups.map((group) => {
                      const isSelected = selectedKnowledgeBaseIds.includes(group.id);
                      const isExpanded = expandedModalKbIds[group.id] ?? false;
                      return (
                        <div
                          key={group.id}
                          className={cn(
                            "rounded-md border",
                            isSelected && "border-primary bg-muted/30",
                          )}
                        >
                          <div className="flex items-center justify-between px-3 py-2">
                            <button
                              type="button"
                              className="flex min-w-0 items-center gap-2 text-left"
                              onClick={() =>
                                setExpandedModalKbIds((prev) => ({
                                  ...prev,
                                  [group.id]: !isExpanded,
                                }))
                              }
                            >
                              <ForwardedIconComponent
                                name={isExpanded ? "ChevronDown" : "ChevronRight"}
                                className="h-4 w-4"
                              />
                              <span className="truncate font-medium">{group.name}</span>
                              <span className="text-xs text-muted-foreground">
                                ({group.files.length} files)
                              </span>
                            </button>
                            <Button
                              size="sm"
                              variant={isSelected ? "default" : "outline"}
                              onClick={() => {
                                if (isList) {
                                  setSelectedKnowledgeBaseIds((prev) =>
                                    isSelected
                                      ? prev.filter((id) => id !== group.id)
                                      : [...prev, group.id],
                                  );
                                } else {
                                  setSelectedKnowledgeBaseIds(
                                    isSelected ? [] : [group.id],
                                  );
                                }
                              }}
                            >
                              {isSelected ? "Selected" : "Select"}
                            </Button>
                          </div>
                          {isExpanded && (
                            <div className="border-t px-3 py-2">
                              {group.files.length > 0 ? (
                                <FilesRendererComponent files={group.files} />
                              ) : (
                                <div className="text-xs text-muted-foreground">
                                  No files in this knowledge base.
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                    {filteredKnowledgeBaseFileGroups.length === 0 && (
                      <div className="text-sm text-muted-foreground">
                        No knowledge bases found.
                      </div>
                    )}
                  </BaseModal.Content>
                  <BaseModal.Footer
                    submit={{
                      label: "Select",
                      disabled: selectedKnowledgeBaseIds.length === 0,
                      dataTestId: "select-knowledge-base-modal-button",
                    }}
                  />
                </BaseModal>
                {(selectedFiles.length === 0 || isList) && (
                  <div data-testid="input-file-component" className="w-full">
                    <Button
                      disabled={isDisabled}
                      onClick={() => {
                        const selectedPathSet = new Set(
                          selectedFiles.map(normalizePath),
                        );
                        const existingKbIds =
                          files
                            ?.filter((f) =>
                              selectedPathSet.has(normalizePath(f.path)),
                            )
                            .map((f) => f.knowledge_base_id)
                            .filter((kbId): kbId is string => !!kbId) ?? [];
                        setSelectedKnowledgeBaseIds(Array.from(new Set(existingKbIds)));
                        setIsKnowledgeBaseModalOpen(true);
                      }}
                      variant={selectedFiles.length !== 0 ? "ghost" : "default"}
                      size={selectedFiles.length !== 0 ? "iconMd" : "default"}
                      className={cn(
                        selectedFiles.length !== 0
                          ? "hit-area-icon absolute -top-8 right-0"
                          : "w-full",
                        "font-semibold",
                      )}
                      data-testid="button_open_file_management"
                    >
                      {selectedFiles.length !== 0 ? (
                        <ForwardedIconComponent
                          name="Plus"
                          className="icon-size"
                          strokeWidth={ICON_STROKE_WIDTH}
                        />
                      ) : (
                        <div>Select knowledge base{isList ? "s" : ""}</div>
                      )}
                    </Button>
                  </div>
                )}
              </div>
            )
          ) : (
            <div className="relative flex w-full">
              <div className="w-full">
                <input
                  data-testid="input-file-component"
                  type="text"
                  className={cn(
                    "primary-input h-9 w-full cursor-pointer rounded-r-none text-sm focus:border-border focus:outline-none focus:ring-0",
                    !value && "text-placeholder-foreground",
                    editNode && "h-6",
                  )}
                  value={value || "Upload a file..."}
                  readOnly
                  disabled={isDisabled}
                  onClick={handleButtonClick}
                />
              </div>
              <div>
                <Button
                  className={cn(
                    "h-9 w-9 rounded-l-none",
                    value &&
                      "bg-accent-emerald-foreground ring-accent-emerald-foreground hover:bg-accent-emerald-foreground",
                    isDisabled &&
                      "relative top-[1px] h-9 ring-1 ring-border ring-offset-0 hover:ring-border",
                    editNode && "h-6",
                  )}
                  onClick={handleButtonClick}
                  disabled={isDisabled}
                  size="icon"
                  data-testid="button_upload_file"
                >
                  <IconComponent
                    name={value ? "CircleCheckBig" : "Upload"}
                    className={cn(
                      value && "text-background",
                      isDisabled && "text-muted-foreground",
                      "h-4 w-4",
                    )}
                    strokeWidth={2}
                  />
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
