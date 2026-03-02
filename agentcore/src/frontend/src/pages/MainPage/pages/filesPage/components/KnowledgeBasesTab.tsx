import type { ColDef, SelectionChangedEvent } from "ag-grid-community";
import type { AgGridReact } from "ag-grid-react";
import { useQueryClient } from "@tanstack/react-query";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import ShadTooltip from "@/components/common/shadTooltipComponent";
import TableComponent from "@/components/core/parameterRenderComponent/components/tableComponent";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import Loading from "@/components/ui/loading";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useDeleteKnowledgeBase } from "@/controllers/API/queries/knowledge-bases/use-delete-knowledge-base";
import { useUpdateKBVisibility } from "@/controllers/API/queries/knowledge-bases/use-update-kb-visibility";
import {
  type KBVisibility,
  type KnowledgeBaseInfo,
  useGetKnowledgeBases,
} from "@/controllers/API/queries/knowledge-bases/use-get-knowledge-bases";
import { api } from "@/controllers/API/api";
import { getURL } from "@/controllers/API/helpers/constants";
import { useGetFilesV2 } from "@/controllers/API/queries/file-management";
import { createFileUpload } from "@/helpers/create-file-upload";
import useUploadFile from "@/hooks/files/use-upload-file";
import BaseModal from "@/modals/baseModal";
import DeleteConfirmationModal from "@/modals/deleteConfirmationModal";
import useFileSizeValidator from "@/shared/hooks/use-file-size-validator";
import useAlertStore from "@/stores/alertStore";
import { formatFileSize } from "@/utils/stringManipulation";
import { FILE_ICONS } from "@/utils/styleUtils";
import { cn } from "@/utils/utils";
import { AuthContext } from "@/contexts/authContext";
import KnowledgeBaseEmptyState from "./KnowledgeBaseEmptyState";
import KnowledgeBaseSelectionOverlay from "./KnowledgeBaseSelectionOverlay";

interface KnowledgeBasesTabProps {
  quickFilterText: string;
  setQuickFilterText: (text: string) => void;
  selectedFiles: any[];
  setSelectedFiles: (files: any[]) => void;
  quantitySelected: number;
  setQuantitySelected: (quantity: number) => void;
  isShiftPressed: boolean;
}

type DisplayRow = {
  id: string;
  name: string;
  rowType: "kb" | "file";
  // KB fields
  visibility?: string;
  created_by?: string;
  created_by_email?: string | null;
  department_name?: string | null;
  organization_name?: string | null;
  size?: number;
  file_count?: number;
  last_activity?: string | null;
  can_delete?: boolean;
  can_edit?: boolean;
  org_id?: string | null;
  dept_id?: string | null;
  // File fields
  path?: string;
  updated_at?: string;
  created_at?: string;
  // For linking files to their KB
  kbId?: string;
  kbName?: string;
};

type KBVisibilityMode = "private" | "public";
type KBPublicScope = "department" | "organization";

const KnowledgeBasesTab = ({
  quickFilterText,
  setQuickFilterText,
  selectedFiles,
  setSelectedFiles,
  quantitySelected,
  setQuantitySelected,
  isShiftPressed,
}: KnowledgeBasesTabProps) => {
  const tableRef = useRef<AgGridReact<any>>(null);
  const { setErrorData, setSuccessData } = useAlertStore((state) => ({
    setErrorData: state.setErrorData,
    setSuccessData: state.setSuccessData,
  }));

  const { role, userData } = useContext(AuthContext);
  const normalizedRole = (role || userData?.role || "")
    .toLowerCase()
    .replace(/\s+/g, "_");
  const isAdminRole = ["root", "super_admin", "department_admin"].includes(
    normalizedRole,
  );
  const showCreatedBy = ["department_admin", "super_admin", "root"].includes(
    normalizedRole,
  );
  const showDepartment = ["super_admin", "root"].includes(normalizedRole);
  const showOrganization = normalizedRole === "root";

  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [knowledgeBaseToDelete, setKnowledgeBaseToDelete] =
    useState<KnowledgeBaseInfo | null>(null);
  const [fileToDelete, setFileToDelete] = useState<DisplayRow | null>(null);
  const [isFileDeleteModalOpen, setIsFileDeleteModalOpen] = useState(false);
  const [isEditVisibilityModalOpen, setIsEditVisibilityModalOpen] = useState(false);
  const [knowledgeBaseToEdit, setKnowledgeBaseToEdit] = useState<KnowledgeBaseInfo | null>(null);

  // Upload modal state
  const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
  const [knowledgeBaseName, setKnowledgeBaseName] = useState("");
  const [isExistingKB, setIsExistingKB] = useState(false);
  const [visibilityMode, setVisibilityMode] = useState<KBVisibilityMode>("private");
  const [publicScope, setPublicScope] = useState<KBPublicScope>("department");
  const [selectedVisibility, setSelectedVisibility] = useState<KBVisibility>("PRIVATE");
  const [selectedOrgId, setSelectedOrgId] = useState("");
  const [selectedDeptId, setSelectedDeptId] = useState("");
  const [visibilityOptions, setVisibilityOptions] = useState<{
    organizations: { id: string; name: string }[];
    departments: { id: string; name: string; org_id: string }[];
  }>({ organizations: [], departments: [] });
  const [pendingUploadFiles, setPendingUploadFiles] = useState<File[]>([]);
  const { validateFileSize } = useFileSizeValidator();
  const uploadFile = useUploadFile({ multiple: true });

  // Expandable rows state
  const [expandedKBs, setExpandedKBs] = useState<Record<string, boolean>>({});

  const queryClient = useQueryClient();
  const { data: knowledgeBases, isLoading, error } = useGetKnowledgeBases();
  const { data: files } = useGetFilesV2();
  const [isDeletingFile, setIsDeletingFile] = useState(false);
  const updateVisibilityMutation = useUpdateKBVisibility(
    { kb_id: knowledgeBaseToEdit?.id || "" },
    {
      onSuccess: () => {
        setSuccessData({ title: "Knowledge base visibility updated successfully" });
        setIsEditVisibilityModalOpen(false);
        setKnowledgeBaseToEdit(null);
      },
      onError: (error: any) => {
        setErrorData({
          title: "Failed to update visibility",
          list: [error?.response?.data?.detail || "Unexpected error"],
        });
      },
    },
  );

  const deleteKnowledgeBaseMutation = useDeleteKnowledgeBase(
    {
      kb_name: knowledgeBaseToDelete?.id || "",
    },
    {
      onSuccess: () => {
        setSuccessData({
          title: `Knowledge Base "${knowledgeBaseToDelete?.name}" deleted successfully!`,
        });
        queryClient.invalidateQueries({ queryKey: ["useGetFilesV2"] });
        resetDeleteState();
      },
      onError: (error: any) => {
        setErrorData({
          title: "Failed to delete knowledge base",
          list: [
            error?.response?.data?.detail ||
              error?.message ||
              "An unknown error occurred",
          ],
        });
        resetDeleteState();
      },
    },
  );

  if (error) {
    setErrorData({
      title: "Failed to load knowledge bases",
      list: [error?.message || "An unknown error occurred"],
    });
  }

  const resetDeleteState = () => {
    setKnowledgeBaseToDelete(null);
    setIsDeleteModalOpen(false);
  };

  const handleDelete = (knowledgeBase: KnowledgeBaseInfo) => {
    setKnowledgeBaseToDelete(knowledgeBase);
    setIsDeleteModalOpen(true);
  };

  const confirmDelete = () => {
    if (knowledgeBaseToDelete && !deleteKnowledgeBaseMutation.isPending) {
      deleteKnowledgeBaseMutation.mutate();
    }
  };

  const handleDeleteFile = (file: DisplayRow) => {
    setFileToDelete(file);
    setIsFileDeleteModalOpen(true);
  };

  const openEditVisibilityModal = (kb: KnowledgeBaseInfo) => {
    setKnowledgeBaseToEdit(kb);
    const kbVisibility = (kb.visibility as KBVisibility) || "PRIVATE";
    setSelectedVisibility(kbVisibility);
    setVisibilityMode(kbVisibility === "PRIVATE" ? "private" : "public");
    setPublicScope(kbVisibility === "ORGANIZATION" ? "organization" : "department");
    setSelectedOrgId(kb.org_id || "");
    setSelectedDeptId(kb.dept_id || "");
    setIsEditVisibilityModalOpen(true);
  };

  const confirmDeleteFile = async () => {
    if (!fileToDelete || isDeletingFile) return;
    setIsDeletingFile(true);
    try {
      await api.delete(
        `${getURL("FILE_MANAGEMENT", { id: fileToDelete.id }, true)}`,
      );
      setSuccessData({
        title: `File "${fileToDelete.name}" deleted successfully!`,
      });
      queryClient.invalidateQueries({ queryKey: ["useGetFilesV2"] });
      queryClient.invalidateQueries({ queryKey: ["useGetKnowledgeBases"] });
    } catch (error: any) {
      setErrorData({
        title: "Failed to delete file",
        list: [
          error?.response?.data?.detail ||
            error?.message ||
            "An unknown error occurred",
        ],
      });
    } finally {
      setIsDeletingFile(false);
      setFileToDelete(null);
      setIsFileDeleteModalOpen(false);
    }
  };

  const handleSelectionChange = (event: SelectionChangedEvent) => {
    const selectedRows = event.api.getSelectedRows();
    setSelectedFiles(selectedRows);
    if (selectedRows.length > 0) {
      setQuantitySelected(selectedRows.length);
    } else {
      setTimeout(() => {
        setQuantitySelected(0);
      }, 300);
    }
  };

  useEffect(() => {
    if (!isUploadModalOpen) {
      setPendingUploadFiles([]);
      setKnowledgeBaseName("");
      setVisibilityMode("private");
      setPublicScope("department");
      setSelectedVisibility("PRIVATE");
      setSelectedOrgId("");
      setSelectedDeptId("");
      setIsExistingKB(false);
    }
  }, [isUploadModalOpen]);

  useEffect(() => {
    if ((!isUploadModalOpen || isExistingKB) && !isEditVisibilityModalOpen) return;
    api.get(`${getURL("KNOWLEDGE_BASES")}/visibility-options`).then((res) => {
      const options = res.data || { organizations: [], departments: [] };
      setVisibilityOptions(options);
      setSelectedOrgId((prev) => prev || options.organizations?.[0]?.id || "");
      setSelectedDeptId((prev) => prev || options.departments?.[0]?.id || "");
    });
  }, [isUploadModalOpen, isExistingKB, isEditVisibilityModalOpen]);

  useEffect(() => {
    setSelectedVisibility(
      visibilityMode === "private"
        ? "PRIVATE"
        : publicScope === "organization"
          ? "ORGANIZATION"
          : "DEPARTMENT",
    );
  }, [visibilityMode, publicScope]);

  useEffect(() => {
    if (visibilityMode !== "public") return;
    if (
      publicScope === "organization" &&
      (normalizedRole === "developer" || normalizedRole === "department_admin") &&
      !selectedOrgId &&
      visibilityOptions.organizations.length > 0
    ) {
      setSelectedOrgId(visibilityOptions.organizations[0].id);
      return;
    }
    if (
      publicScope === "department" &&
      normalizedRole !== "super_admin" &&
      normalizedRole !== "root" &&
      !selectedDeptId &&
      visibilityOptions.departments.length > 0
    ) {
      const dept = visibilityOptions.departments[0];
      setSelectedDeptId(dept.id);
      if (!selectedOrgId) setSelectedOrgId(dept.org_id);
    }
  }, [
    visibilityMode,
    publicScope,
    normalizedRole,
    selectedOrgId,
    selectedDeptId,
    visibilityOptions.organizations,
    visibilityOptions.departments,
  ]);

  const handleUpload = async (
    uploadFiles?: File[],
    kbName?: string,
    visibility?: string,
    scope?: {
      public_scope?: "organization" | "department";
      org_id?: string;
      dept_id?: string;
    },
  ) => {
    try {
      const filesIds = await uploadFile({
        files: uploadFiles,
        knowledgeBaseName: kbName,
        visibility,
        public_scope: scope?.public_scope,
        org_id: scope?.org_id,
        dept_id: scope?.dept_id,
      });
      setSuccessData({
        title: `File${filesIds.length > 1 ? "s" : ""} uploaded successfully`,
      });
    } catch (error: any) {
      setErrorData({
        title: "Error uploading file",
        list: [error.message || "An error occurred while uploading the file"],
      });
    }
  };

  const handleOpenUploadModal = () => {
    setIsExistingKB(false);
    setKnowledgeBaseName("");
    setVisibilityMode("private");
    setPublicScope("department");
    setSelectedVisibility("PRIVATE");
    setSelectedOrgId("");
    setSelectedDeptId("");
    setIsUploadModalOpen(true);
  };

  const handleUploadMoreToKB = (kb: KnowledgeBaseInfo) => {
    setIsExistingKB(true);
    setKnowledgeBaseName(kb.name);
    setSelectedVisibility((kb.visibility as KBVisibility) || "PRIVATE");
    setIsUploadModalOpen(true);
  };

  const handleChooseFiles = async () => {
    try {
      const selected = await createFileUpload({
        multiple: true,
        accept: "",
      });
      const validFiles: File[] = [];
      for (const file of selected) {
        validateFileSize(file);
        validFiles.push(file);
      }
      setPendingUploadFiles((prev) => [...prev, ...validFiles]);
    } catch (error: any) {
      setErrorData({
        title: "Error selecting files",
        list: [error.message || "Could not select files"],
      });
    }
  };

  const removeFile = (index: number) => {
    setPendingUploadFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const clearSelection = () => {
    setQuantitySelected(0);
    setSelectedFiles([]);
  };

  // Helper to extract KB name from file path
  const getKBNameFromPath = (path: string) => {
    const normalizedPath = path.replace(/\\/g, "/");
    const segments = normalizedPath.split("/").filter(Boolean);
    // Legacy: <user_id>/<kb_name>/<file>
    // New:    <user_id>/<kb_id>/<kb_name>/<file>
    if (segments.length >= 4) return segments[2];
    if (segments.length >= 3) return segments[1];
    return null;
  };

  // Build display rows: KB rows + expandable file rows
  const displayRows: DisplayRow[] = useMemo(() => {
    if (!knowledgeBases || !Array.isArray(knowledgeBases)) return [];

    const filesByKBId = new Map<string, any[]>();
    const filesByKBName = new Map<string, any[]>();
    if (files && Array.isArray(files)) {
      files.forEach((file: any) => {
        if (file.knowledge_base_id) {
          const existingById = filesByKBId.get(file.knowledge_base_id) ?? [];
          existingById.push(file);
          filesByKBId.set(file.knowledge_base_id, existingById);
        }
        const kbName = getKBNameFromPath(file.path);
        if (kbName) {
          const existingByName = filesByKBName.get(kbName) ?? [];
          existingByName.push(file);
          filesByKBName.set(kbName, existingByName);
        }
      });
    }

    const rows: DisplayRow[] = [];
    knowledgeBases.forEach((kb) => {
      const canDelete = isAdminRole || kb.created_by === userData?.id;
      const canEdit = isAdminRole || kb.created_by === userData?.id;
      rows.push({
        id: kb.id,
        name: kb.name,
        rowType: "kb",
        visibility: kb.visibility,
        created_by: kb.created_by,
        created_by_email: kb.created_by_email,
        department_name: kb.department_name,
        organization_name: kb.organization_name,
        org_id: kb.org_id,
        dept_id: kb.dept_id,
        size: kb.size,
        file_count: kb.file_count,
        last_activity: kb.last_activity ?? kb.updated_at ?? null,
        can_delete: canDelete,
        can_edit: canEdit,
      });

      if (expandedKBs[kb.id]) {
        const kbFiles = filesByKBId.get(kb.id) ?? filesByKBName.get(kb.name) ?? [];
        kbFiles.forEach((file) => {
          rows.push({
            id: file.id,
            name: file.name,
            rowType: "file",
            path: file.path,
            size: file.size,
            updated_at: file.updated_at,
            created_at: file.created_at,
            kbId: kb.id,
            kbName: kb.name,
            can_delete: canDelete,
          });
        });
      }
    });

    return rows;
  }, [knowledgeBases, files, expandedKBs, isAdminRole, userData?.id]);

  // Column definitions with expandable KB rows
  const columnDefs: ColDef[] = useMemo(() => {
    const baseCellClass =
      "text-muted-foreground cursor-pointer select-text group-[.no-select-cells]:cursor-default group-[.no-select-cells]:select-none";

    return [
      {
        headerName: "Name",
        field: "name",
        flex: 3,
        sortable: false,
        headerCheckboxSelection: true,
        checkboxSelection: (params: any) => params.data?.rowType === "kb",
        editable: false,
        filter: "agTextColumnFilter",
        cellClass: baseCellClass,
        cellRenderer: (params: any) => {
          if (params.data.rowType === "kb") {
            const isExpanded = expandedKBs[params.data.id];
            const fileCount = params.data.file_count ?? 0;
            return (
              <div className="flex w-full items-center justify-between">
                <div className="flex items-center gap-2 font-medium">
                  <button
                    className="flex items-center"
                    onClick={(e) => {
                      e.stopPropagation();
                      setExpandedKBs((prev) => ({
                        ...prev,
                        [params.data.id]: !isExpanded,
                      }));
                    }}
                  >
                    <ForwardedIconComponent
                      name={isExpanded ? "ChevronDown" : "ChevronRight"}
                      className="h-4 w-4"
                    />
                  </button>
                  <ForwardedIconComponent
                    name="Folder"
                    className="h-4 w-4"
                  />
                  <span className="text-sm font-medium">{params.value}</span>
                  <span className="text-xs text-muted-foreground">
                    ({fileCount} file{fileCount !== 1 ? "s" : ""})
                  </span>
                </div>
                <ShadTooltip content="Add files to this knowledge base" side="left">
                  <button
                    className="ml-2 flex items-center rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                    onClick={(e) => {
                      e.stopPropagation();
                      const kb = knowledgeBases?.find(
                        (k) => k.id === params.data.id,
                      );
                      if (kb) handleUploadMoreToKB(kb);
                    }}
                  >
                    <ForwardedIconComponent
                      name="Upload"
                      className="h-3.5 w-3.5"
                    />
                  </button>
                </ShadTooltip>
              </div>
            );
          }

          const type =
            params.data.path?.split(".").pop()?.toLowerCase() ?? "";
          return (
            <div className="flex w-full items-center justify-between">
              <div className="flex items-center gap-3 pl-10 font-medium">
                <ForwardedIconComponent
                  name={FILE_ICONS[type]?.icon ?? "File"}
                  className={cn(
                    "h-5 w-5 shrink-0",
                    FILE_ICONS[type]?.color ?? undefined,
                  )}
                />
                <span className="text-sm">
                  {params.value}
                  {type ? `.${type}` : ""}
                </span>
              </div>
              <ShadTooltip content="Delete file" side="left">
                {params.data?.can_delete ? (
                  <button
                    className="ml-2 flex items-center rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-destructive"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDeleteFile(params.data);
                    }}
                  >
                    <ForwardedIconComponent
                      name="Trash2"
                      className="h-3.5 w-3.5"
                    />
                  </button>
                ) : (
                  <span className="ml-2 h-6 w-6" />
                )}
              </ShadTooltip>
            </div>
          );
        },
      },
      {
        headerName: "Visibility",
        field: "visibility",
        flex: 1,
        sortable: false,
        filter: "agTextColumnFilter",
        editable: false,
        cellClass: baseCellClass,
        valueGetter: (params: any) => {
          if (params.data?.rowType === "file") return "";
          const v = params.data?.visibility || "PRIVATE";
          const labels: Record<string, string> = {
            PRIVATE: "Private",
            DEPARTMENT: "Department",
            ORGANIZATION: "Organization",
          };
          return labels[v] || v;
        },
      },
      {
        headerName: "Actions",
        field: "actions",
        flex: 0.8,
        sortable: false,
        filter: false,
        editable: false,
        cellClass: baseCellClass,
        cellRenderer: (params: any) => {
          if (params.data?.rowType !== "kb" || !params.data?.can_edit) return "";
          return (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2"
              onClick={(e) => {
                e.stopPropagation();
                const kb = knowledgeBases?.find((k) => k.id === params.data.id);
                if (kb) openEditVisibilityModal(kb);
              }}
            >
              Edit Visibility
            </Button>
          );
        },
      },
      {
        headerName: "Size",
        field: "size",
        flex: 1,
        sortable: false,
        editable: false,
        cellClass: baseCellClass,
        valueFormatter: (params: any) => {
          if (params.value == null) return "";
          return formatFileSize(params.value);
        },
      },
      {
        headerName: "Modified",
        field: "last_activity",
        flex: 1,
        sortable: false,
        editable: false,
        cellClass: baseCellClass,
        valueFormatter: (params: any) => {
          const rawValue =
            params.data?.rowType === "kb"
              ? params.data?.last_activity
              : params.data?.updated_at;
          if (!rawValue) return "";
          const hasTimezone = /(?:[zZ]|[+-]\d{2}:\d{2})$/.test(rawValue);
          return new Date(hasTimezone ? rawValue : `${rawValue}Z`).toLocaleString();
        },
      },
      ...(showCreatedBy
        ? [
            {
              headerName: "Created By",
              field: "created_by_email",
              flex: 1.2,
              sortable: false,
              editable: false,
              cellClass: baseCellClass,
              valueGetter: (params: any) =>
                params.data?.rowType === "kb" ? (params.data?.created_by_email || "--") : "",
            } as ColDef,
          ]
        : []),
      ...(showDepartment
        ? [
            {
              headerName: "Department",
              field: "department_name",
              flex: 1.2,
              sortable: false,
              editable: false,
              cellClass: baseCellClass,
              valueGetter: (params: any) =>
                params.data?.rowType === "kb" ? (params.data?.department_name || "--") : "",
            } as ColDef,
          ]
        : []),
      ...(showOrganization
        ? [
            {
              headerName: "Organization",
              field: "organization_name",
              flex: 1.2,
              sortable: false,
              editable: false,
              cellClass: baseCellClass,
              valueGetter: (params: any) =>
                params.data?.rowType === "kb" ? (params.data?.organization_name || "--") : "",
            } as ColDef,
          ]
        : []),
    ];
  }, [expandedKBs, knowledgeBases, showCreatedBy, showDepartment, showOrganization]);

  if (isLoading || !knowledgeBases || !Array.isArray(knowledgeBases)) {
    return (
      <div className="flex h-full w-full items-center justify-center">
        <Loading />
      </div>
    );
  }

  const uploadModal = (
    <BaseModal
      size="small-h-full"
      open={isUploadModalOpen}
      setOpen={setIsUploadModalOpen}
    >
      <BaseModal.Header
        description={
          isExistingKB
            ? `Add more files to "${knowledgeBaseName}"`
            : "Create a new knowledge base by uploading files."
        }
      >
        {isExistingKB ? "Add Files" : "Upload Knowledge Base"}
      </BaseModal.Header>
      <BaseModal.Content>
        <div className="flex flex-col gap-4 px-1">
          {/* KB Name */}
          <div className="space-y-1.5">
            <Label className="text-sm font-medium">Knowledge Base Name</Label>
            <Input
              placeholder="Enter knowledge base name"
              value={knowledgeBaseName}
              onChange={(event) => {
                setKnowledgeBaseName(event.target.value);
              }}
              disabled={isExistingKB}
              data-testid="knowledge-base-name-upload-input"
            />
          </div>

          {/* Visibility */}
          {!isExistingKB && (
            <div className="space-y-1.5">
              <Label className="text-sm font-medium">Visibility</Label>
              <Select
                value={visibilityMode}
                onValueChange={(value) => setVisibilityMode(value as KBVisibilityMode)}
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Select visibility" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="private">Private</SelectItem>
                  <SelectItem value="public">Public</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}

          {!isExistingKB && visibilityMode === "public" && (
            <>
              <div className="space-y-1.5">
                <Label className="text-sm font-medium">Public To</Label>
                <Select
                  value={publicScope}
                  onValueChange={(value) => setPublicScope(value as KBPublicScope)}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Select scope" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="department">Department</SelectItem>
                    <SelectItem value="organization">Organization</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {publicScope === "organization" && (
                <div className="space-y-1.5">
                  <Label className="text-sm font-medium">Organization</Label>
                  <Select
                    value={selectedOrgId}
                    onValueChange={setSelectedOrgId}
                    disabled={normalizedRole === "developer" || normalizedRole === "department_admin"}
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue placeholder="Select organization" />
                    </SelectTrigger>
                    <SelectContent>
                      {visibilityOptions.organizations.map((org) => (
                        <SelectItem key={org.id} value={org.id}>
                          {org.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}

              {publicScope === "department" && (
                <div className="space-y-1.5">
                  <Label className="text-sm font-medium">Department</Label>
                  <Select
                    value={selectedDeptId}
                    onValueChange={(value) => {
                      setSelectedDeptId(value);
                      const dept = visibilityOptions.departments.find((d) => d.id === value);
                      if (dept) setSelectedOrgId(dept.org_id);
                    }}
                    disabled={normalizedRole !== "super_admin" && normalizedRole !== "root"}
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue placeholder="Select department" />
                    </SelectTrigger>
                    <SelectContent>
                      {visibilityOptions.departments
                        .filter((dept) => !selectedOrgId || dept.org_id === selectedOrgId)
                        .map((dept) => (
                          <SelectItem key={dept.id} value={dept.id}>
                            {dept.name}
                          </SelectItem>
                        ))}
                    </SelectContent>
                  </Select>
                </div>
              )}
            </>
          )}

          {/* File selection area */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <Label className="text-sm font-medium">Files</Label>
              <Button
                variant="outline"
                size="sm"
                type="button"
                onClick={handleChooseFiles}
              >
                <ForwardedIconComponent name="Plus" className="mr-1 h-3.5 w-3.5" />
                Choose Files
              </Button>
            </div>

            {pendingUploadFiles.length === 0 ? (
              <div
                className="flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed border-muted-foreground/25 px-6 py-8 text-center transition-colors hover:border-muted-foreground/50"
                onClick={handleChooseFiles}
              >
                <ForwardedIconComponent
                  name="Upload"
                  className="mb-2 h-8 w-8 text-muted-foreground/50"
                />
                <p className="text-sm text-muted-foreground">
                  Click to select files or use the button above
                </p>
              </div>
            ) : (
              <div className="max-h-52 overflow-auto rounded-lg border">
                <div className="flex flex-col divide-y">
                  {pendingUploadFiles.map((file, index) => {
                    const fileType =
                      file.name.split(".").pop()?.toLowerCase() ?? "";
                    const fileIcon = FILE_ICONS[fileType]?.icon ?? "File";
                    const fileIconColor =
                      FILE_ICONS[fileType]?.color ?? "text-muted-foreground";

                    return (
                      <div
                        key={`${file.name}-${file.size}-${index}`}
                        className="flex items-center justify-between px-3 py-2"
                      >
                        <div className="flex min-w-0 items-center gap-2.5">
                          <ForwardedIconComponent
                            name={fileIcon}
                            className={cn("h-4 w-4 shrink-0", fileIconColor)}
                          />
                          <span className="truncate text-sm font-medium">
                            {file.name}
                          </span>
                        </div>
                        <div className="ml-3 flex shrink-0 items-center gap-2">
                          <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase text-muted-foreground">
                            {fileType || "file"}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            {formatFileSize(file.size)}
                          </span>
                          <button
                            className="ml-1 rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-destructive"
                            onClick={() => removeFile(index)}
                          >
                            <ForwardedIconComponent
                              name="X"
                              className="h-3.5 w-3.5"
                            />
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {pendingUploadFiles.length > 0 && (
              <p className="text-xs text-muted-foreground">
                {pendingUploadFiles.length} file
                {pendingUploadFiles.length !== 1 ? "s" : ""} selected
                {" \u00B7 "}
                {formatFileSize(
                  pendingUploadFiles.reduce((acc, f) => acc + f.size, 0),
                )}{" "}
                total
              </p>
            )}
          </div>
        </div>
      </BaseModal.Content>
      <BaseModal.Footer
        submit={{
          label: isExistingKB ? "Upload Files" : "Upload Knowledge Base",
          dataTestId: "upload-files-with-kb-button",
          disabled:
            pendingUploadFiles.length === 0 ||
            !knowledgeBaseName.trim() ||
            (visibilityMode === "public" &&
              ((publicScope === "organization" && !selectedOrgId) ||
                (publicScope === "department" && !selectedDeptId))),
          onClick: async () => {
            const kbName = knowledgeBaseName.trim();
            if (!kbName) {
              setErrorData({
                title: "Knowledge base name is required",
              });
              return;
            }
            const uploadScope =
              visibilityMode === "public"
                ? {
                    public_scope: publicScope,
                    org_id: publicScope === "organization" ? selectedOrgId : undefined,
                    dept_id: publicScope === "department" ? selectedDeptId : undefined,
                  }
                : undefined;
            await handleUpload(pendingUploadFiles, kbName, selectedVisibility, uploadScope);
            setIsUploadModalOpen(false);
          },
        }}
      >
        <></>
      </BaseModal.Footer>
    </BaseModal>
  );

  if (knowledgeBases.length === 0) {
    return (
      <>
        <KnowledgeBaseEmptyState
          handleCreateKnowledge={handleOpenUploadModal}
        />
        {uploadModal}
      </>
    );
  }

  return (
    <div className="flex h-full flex-col pb-4">
      <div className="flex justify-between">
        <div className="flex w-full xl:w-5/12">
          <Input
            icon="Search"
            data-testid="search-kb-input"
            type="text"
            placeholder="Search knowledge bases..."
            className="mr-2 w-full"
            value={quickFilterText || ""}
            onChange={(event) => setQuickFilterText(event.target.value)}
          />
        </div>
        <Button
          className="flex items-center gap-2 font-semibold"
          onClick={handleOpenUploadModal}
        >
          <ForwardedIconComponent name="Plus" /> Upload Knowledge Base
        </Button>
      </div>

      <div className="flex h-full flex-col pt-4">
        <div className="relative h-full">
          <TableComponent
            rowHeight={45}
            headerHeight={45}
            cellSelection={false}
            tableOptions={{
              hide_options: true,
            }}
            suppressRowClickSelection={!isShiftPressed}
            rowSelection="multiple"
            onSelectionChanged={handleSelectionChange}
            columnDefs={columnDefs}
            rowData={displayRows}
            className={cn(
              "ag-no-border ag-knowledge-table group w-full",
              isShiftPressed && quantitySelected > 0 && "no-select-cells",
            )}
            pagination
            ref={tableRef}
            quickFilterText={quickFilterText}
            gridOptions={{
              stopEditingWhenCellsLoseFocus: true,
              ensureDomOrder: true,
              colResizeDefault: "shift",
              isRowSelectable: (params: any) =>
                params.data?.rowType === "kb" && !!params.data?.can_delete,
            }}
          />

          <KnowledgeBaseSelectionOverlay
            selectedFiles={selectedFiles}
            quantitySelected={quantitySelected}
            onClearSelection={clearSelection}
          />
        </div>
      </div>

      <DeleteConfirmationModal
        open={isDeleteModalOpen}
        setOpen={setIsDeleteModalOpen}
        onConfirm={confirmDelete}
        description={`knowledge base "${knowledgeBaseToDelete?.name || ""}"`}
        note="This action cannot be undone"
      >
        <></>
      </DeleteConfirmationModal>

      <DeleteConfirmationModal
        open={isFileDeleteModalOpen}
        setOpen={setIsFileDeleteModalOpen}
        onConfirm={confirmDeleteFile}
        description={`file "${fileToDelete?.name || ""}"`}
        note="This action cannot be undone"
      >
        <></>
      </DeleteConfirmationModal>

      <BaseModal
        size="small-h-full"
        open={isEditVisibilityModalOpen}
        setOpen={setIsEditVisibilityModalOpen}
      >
        <BaseModal.Header description="Update visibility scope for this knowledge base.">
          Edit Visibility
        </BaseModal.Header>
        <BaseModal.Content>
          <div className="flex flex-col gap-4 px-1">
            <div className="space-y-1.5">
              <Label className="text-sm font-medium">Visibility</Label>
              <Select
                value={visibilityMode}
                onValueChange={(value) => setVisibilityMode(value as KBVisibilityMode)}
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Select visibility" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="private">Private</SelectItem>
                  <SelectItem value="public">Public</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {visibilityMode === "public" && (
              <>
                <div className="space-y-1.5">
                  <Label className="text-sm font-medium">Public To</Label>
                  <Select
                    value={publicScope}
                    onValueChange={(value) => setPublicScope(value as KBPublicScope)}
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue placeholder="Select scope" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="department">Department</SelectItem>
                      <SelectItem value="organization">Organization</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                {publicScope === "organization" && (
                  <div className="space-y-1.5">
                    <Label className="text-sm font-medium">Organization</Label>
                    <Select
                      value={selectedOrgId}
                      onValueChange={setSelectedOrgId}
                      disabled={normalizedRole === "developer" || normalizedRole === "department_admin"}
                    >
                      <SelectTrigger className="w-full">
                        <SelectValue placeholder="Select organization" />
                      </SelectTrigger>
                      <SelectContent>
                        {visibilityOptions.organizations.map((org) => (
                          <SelectItem key={org.id} value={org.id}>
                            {org.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}

                {publicScope === "department" && (
                  <div className="space-y-1.5">
                    <Label className="text-sm font-medium">Department</Label>
                    <Select
                      value={selectedDeptId}
                      onValueChange={(value) => {
                        setSelectedDeptId(value);
                        const dept = visibilityOptions.departments.find((d) => d.id === value);
                        if (dept) setSelectedOrgId(dept.org_id);
                      }}
                      disabled={normalizedRole !== "super_admin" && normalizedRole !== "root"}
                    >
                      <SelectTrigger className="w-full">
                        <SelectValue placeholder="Select department" />
                      </SelectTrigger>
                      <SelectContent>
                        {visibilityOptions.departments
                          .filter((dept) => !selectedOrgId || dept.org_id === selectedOrgId)
                          .map((dept) => (
                            <SelectItem key={dept.id} value={dept.id}>
                              {dept.name}
                            </SelectItem>
                          ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}
              </>
            )}
          </div>
        </BaseModal.Content>
        <BaseModal.Footer
          submit={{
            label: "Save",
            disabled:
              updateVisibilityMutation.isPending ||
              (visibilityMode === "public" &&
                ((publicScope === "organization" && !selectedOrgId) ||
                  (publicScope === "department" && !selectedDeptId))),
            onClick: async () => {
              if (!knowledgeBaseToEdit) return;
              await updateVisibilityMutation.mutateAsync({
                visibility: selectedVisibility,
                public_scope: visibilityMode === "public" ? publicScope : undefined,
                org_id:
                  visibilityMode === "public" && publicScope === "organization"
                    ? selectedOrgId
                    : undefined,
                dept_id:
                  visibilityMode === "public" && publicScope === "department"
                    ? selectedDeptId
                    : undefined,
              });
            },
          }}
        >
          <></>
        </BaseModal.Footer>
      </BaseModal>

      {uploadModal}
    </div>
  );
};

export default KnowledgeBasesTab;
