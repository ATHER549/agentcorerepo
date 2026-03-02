import * as Form from "@radix-ui/react-form";
import { useContext, useEffect, useState } from "react";
import IconComponent from "@/components/common/genericIconComponent";
import { Button } from "../../components/ui/button";
import { Checkbox } from "../../components/ui/checkbox";
import { CONTROL_NEW_USER } from "../../constants/constants";
import { AuthContext } from "../../contexts/authContext";
import {
  useGetAssignableRoles,
  useGetDepartments,
} from "../../controllers/API/queries/auth";
import type {
  inputHandlerEventType,
  UserInputType,
  UserManagementType,
} from "../../types/components";
import BaseModal from "../baseModal";

export default function UserManagementModal({
  title,
  titleHeader,
  cancelText,
  confirmationText,
  children,
  icon,
  data,
  index,
  onConfirm,
  asChild,
}: UserManagementType) {
  const [open, setOpen] = useState(false);
  const [username, setUserName] = useState(data?.username ?? "");
  const [isActive, setIsActive] = useState(data?.is_active ?? false);
  const [selectedRole, setSelectedRole] = useState(
    data?.role ?? "business_user",
  );
  const [availableRoles, setAvailableRoles] = useState<string[]>([]);
  const [departmentId, setDepartmentId] = useState("");
  const [departments, setDepartments] = useState<Array<{ id: string; name: string }>>([]);
  const [departmentName, setDepartmentName] = useState("");
  const [organizationName, setOrganizationName] = useState("");
  const [organizationDescription, setOrganizationDescription] = useState("");
  const [departmentError, setDepartmentError] = useState("");
  const [organizationError, setOrganizationError] = useState("");
  const { mutate: mutateGetAssignableRoles } = useGetAssignableRoles();
  const { mutate: mutateGetDepartments } = useGetDepartments();
  const [inputState, setInputState] = useState<UserInputType>(CONTROL_NEW_USER);
  const { userData } = useContext(AuthContext);

  const getDefaultRoleForCreator = () => {
    if (userData?.role === "root") return "super_admin";
    return "business_user";
  };

  function handleInput({
    target: { name, value },
  }: inputHandlerEventType): void {
    setInputState((prev) => ({ ...prev, [name]: value }));
  }

  useEffect(() => {
    if (open) {
      if (!data) {
        resetForm();
      } else {
        setUserName(data.username);
        setIsActive(data.is_active);
        const nextRole = data.role ?? "business_user";
        setSelectedRole(nextRole);
        setDepartmentId(data.department_id ?? "");
        setDepartmentName(data.department_name ?? "");
        setOrganizationName(data.organization_name ?? "");
        setOrganizationDescription(data.organization_description ?? "");
        setDepartmentError("");
        setOrganizationError("");

        handleInput({ target: { name: "username", value: data.username } });
        handleInput({ target: { name: "is_active", value: data.is_active } });
        handleInput({ target: { name: "role", value: nextRole } });
      }
    }
  }, [open, data]);

  useEffect(() => {
    if (open) {
      mutateGetAssignableRoles(undefined, {
        onSuccess: (roleNames) => {
          const fallbackRoles = ["super_admin", "department_admin", "developer", "business_user"];
          const merged = (roleNames || []).length > 0 ? (roleNames || []) : fallbackRoles;
          const withSelected = merged.includes(selectedRole)
            ? merged
            : [...merged, selectedRole];
          setAvailableRoles(withSelected);
        },
        onError: () => {
          // Fallback roles if API fails
          const fallbackRoles = ["super_admin", "department_admin", "developer", "business_user"];
          setAvailableRoles(fallbackRoles);
        },
      });
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    if (userData?.role !== "super_admin") return;
    mutateGetDepartments(undefined, {
      onSuccess: (res) => {
        setDepartments((res ?? []).map((dept) => ({ id: dept.id, name: dept.name })));
      },
      onError: () => {
        setDepartments([]);
      },
    });
  }, [open, userData?.role]);

  function resetForm() {
    const defaultRole = getDefaultRoleForCreator();
    setUserName("");
    setIsActive(false);
    setSelectedRole(defaultRole);
    setDepartmentId("");
    setDepartmentName("");
    setOrganizationName("");
    setOrganizationDescription("");
    setDepartmentError("");
    setOrganizationError("");
    setInputState({ ...CONTROL_NEW_USER, role: defaultRole });
  }

  function handleRoleChange(selectedRole: string) {
    setSelectedRole(selectedRole);
    handleInput({ target: { name: "role", value: selectedRole } });
    setAvailableRoles((prev) => {
      if (!prev || prev.length === 0) return prev;
      return prev.includes(selectedRole) ? prev : [...prev, selectedRole];
    });
    if (selectedRole === "department_admin") {
      setDepartmentId("");
      setDepartmentError("");
    }
  }

  // Helper function to format role for display
  function formatRoleDisplay(role: string) {
    return role.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase());
  }

  const isRootAdmin = userData?.role === "root";
  const effectiveRole = isRootAdmin ? "super_admin" : (selectedRole || "business_user");
  const isSuperAdmin = userData?.role === "super_admin";
  const isDepartmentAdminCreator = userData?.role === "department_admin";
  const isCreatingSuperAdmin = effectiveRole === "super_admin";
  const isCreatingDepartmentAdmin = effectiveRole === "department_admin";
  const requiresOrganizationBootstrap = isRootAdmin && isCreatingSuperAdmin;
  const requiresDepartmentAdminSelection =
    isSuperAdmin && !isCreatingDepartmentAdmin;
  const rolesToRender = (() => {
    let baseRoles: string[] = [];
    if (isRootAdmin) {
      baseRoles = ["super_admin"];
    } else if (isSuperAdmin) {
      baseRoles =
        availableRoles.length > 0
          ? availableRoles.filter((role) => !["root", "super_admin"].includes(role))
          : ["department_admin", "developer", "business_user"];
    } else if (isDepartmentAdminCreator) {
      baseRoles = ["developer", "business_user"];
    } else if (availableRoles.length > 0) {
      baseRoles = availableRoles;
    } else {
      baseRoles = ["super_admin", "department_admin", "developer", "business_user"];
    }
    if (isRootAdmin) {
      return ["super_admin"];
    }
    return Array.from(new Set([...baseRoles, effectiveRole].filter(Boolean)));
  })();

  function validateDepartmentAdminSelection(): boolean {
    if (!requiresDepartmentAdminSelection) return true;
    if (!departmentId) {
      setDepartmentError("Please select a department.");
      return false;
    }
    const exists = departments.some((dept) => dept.id === departmentId);
    if (!exists) {
      setDepartmentError("Please select a valid department.");
      return false;
    }
    setDepartmentError("");
    return true;
  }

  return (
    <BaseModal size="medium-h-full" open={open} setOpen={setOpen}>
      <BaseModal.Trigger asChild={asChild}>{children}</BaseModal.Trigger>
      <BaseModal.Header description={titleHeader}>
        <span className="pr-2">{title}</span>
        <IconComponent
          name={icon}
          className="h-6 w-6 pl-1 text-foreground"
          aria-hidden="true"
        />
      </BaseModal.Header>
      <BaseModal.Content>
        <Form.Root
          onSubmit={(event) => {
            const submitRequiresDepartmentAdminSelection =
              userData?.role === "super_admin" && effectiveRole !== "department_admin";
            if (submitRequiresDepartmentAdminSelection && !validateDepartmentAdminSelection()) {
              event.preventDefault();
              return;
            }
            if (requiresOrganizationBootstrap && !organizationName.trim()) {
              setOrganizationError("Organization name is required.");
              event.preventDefault();
              return;
            }
            const submitData = {
              ...inputState,
              username,
              is_active: isActive,
              role: effectiveRole,
            };

            if (isCreatingDepartmentAdmin) {
              submitData.department_name = departmentName;
              submitData.department_admin_email = "";
              delete submitData.department_id;
            } else if (isDepartmentAdminCreator) {
              submitData.department_admin_email = userData?.username || "";
              submitData.department_name =
                (userData as any)?.department_name || "";
              if ((userData as any)?.department_id) {
                submitData.department_id = (userData as any).department_id;
              } else {
                delete submitData.department_id;
              }
            } else if (requiresDepartmentAdminSelection) {
              submitData.department_id = departmentId;
              submitData.department_admin_email = "";
            }
            if (requiresOrganizationBootstrap) {
              submitData.organization_name = organizationName.trim();
              submitData.organization_description = organizationDescription.trim();
            }
            
            resetForm();
            onConfirm(1, submitData);
            setOpen(false);
            event.preventDefault();
          }}
        >
          <div className="grid gap-5">
            <Form.Field name="username">
              <div
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  justifyContent: "space-between",
                }}
              >
                <Form.Label className="data-[invalid]:label-invalid">
                  Username{" "}
                  <span className="font-medium text-destructive">*</span>
                </Form.Label>
              </div>
              <Form.Control asChild>
                <input
                  onChange={({ target: { value } }) => {
                    handleInput({ target: { name: "username", value } });
                    setUserName(value);
                  }}
                  value={username}
                  className="primary-input"
                  required
                  placeholder="Username"
                />
              </Form.Control>
              <Form.Message match="valueMissing" className="field-invalid">
                Please enter your username
              </Form.Message>
            </Form.Field>

            <div className="flex gap-8">
              <Form.Field name="is_active">
                <div>
                  <Form.Label className="data-[invalid]:label-invalid mr-3">
                    Active
                  </Form.Label>
                  <Form.Control asChild>
                    <Checkbox
                      value={isActive}
                      checked={isActive}
                      id="is_active"
                      className="relative top-0.5"
                      onCheckedChange={(value) => {
                        handleInput({ target: { name: "is_active", value } });
                        setIsActive(value);
                      }}
                    />
                  </Form.Control>
                </div>
              </Form.Field>
              
              <Form.Field name="role">
                <div className="flex flex-col">
                  <Form.Label className="data-[invalid]:label-invalid mb-2">
                    Role{" "}
                    <span className="font-medium text-destructive">*</span>
                  </Form.Label>
                  <select
                    value={effectiveRole}
                    name="role"
                    onChange={(e) => handleRoleChange(e.target.value)}
                    className="primary-input cursor-pointer"
                    required
                  >
                    {rolesToRender.map((r) => (
                      <option key={r} value={r}>
                        {formatRoleDisplay(r)}
                      </option>
                    ))}
                  </select>
                </div>
              </Form.Field>
            </div>

            {isCreatingDepartmentAdmin && (
              <Form.Field name="department_name">
                <div className="flex flex-col">
                  <Form.Label className="data-[invalid]:label-invalid mb-2">
                    Department Name{" "}
                    <span className="font-medium text-destructive">*</span>
                  </Form.Label>
                  <Form.Control asChild>
                    <input
                      onChange={({ target: { value } }) => {
                        setDepartmentName(value);
                      }}
                      value={departmentName}
                      className="primary-input"
                      required
                      placeholder="Department name"
                    />
                  </Form.Control>
                </div>
              </Form.Field>
            )}
            {requiresOrganizationBootstrap && (
              <div className="grid gap-4">
                <Form.Field name="organization_name">
                  <div className="flex flex-col">
                    <Form.Label className="data-[invalid]:label-invalid mb-2">
                      Organization Name{" "}
                      <span className="font-medium text-destructive">*</span>
                    </Form.Label>
                    <Form.Control asChild>
                      <input
                        onChange={({ target: { value } }) => {
                          setOrganizationName(value);
                          setOrganizationError("");
                        }}
                        value={organizationName}
                        className="primary-input"
                        required
                        placeholder="Organization name"
                      />
                    </Form.Control>
                    {organizationError && (
                      <div className="mt-1 text-xs text-destructive">
                        {organizationError}
                      </div>
                    )}
                  </div>
                </Form.Field>
                <Form.Field name="organization_description">
                  <div className="flex flex-col">
                    <Form.Label className="data-[invalid]:label-invalid mb-2">
                      Organization Description
                    </Form.Label>
                    <Form.Control asChild>
                      <input
                        onChange={({ target: { value } }) => {
                          setOrganizationDescription(value);
                        }}
                        value={organizationDescription}
                        className="primary-input"
                        placeholder="Optional description"
                      />
                    </Form.Control>
                  </div>
                </Form.Field>
              </div>
            )}

            {requiresDepartmentAdminSelection && (
              <Form.Field name="department_id">
                <div className="flex flex-col">
                  <Form.Label className="data-[invalid]:label-invalid mb-2">
                    Department{" "}
                    <span className="font-medium text-destructive">*</span>
                  </Form.Label>
                  <select
                    name="department_id"
                    value={departmentId}
                    onChange={(e) => {
                      setDepartmentId(String(e.target.value || ""));
                      setDepartmentError("");
                    }}
                    className="primary-input"
                    required
                  >
                    <option value="">Select department</option>
                    {departments.map((dept) => (
                      <option key={String(dept.id)} value={String(dept.id)}>
                        {dept.name}
                      </option>
                    ))}
                  </select>
                  {departmentError && (
                    <div className="mt-1 text-xs text-destructive">
                      {departmentError}
                    </div>
                  )}
                </div>
              </Form.Field>
            )}
          </div>

          <div className="float-right">
            <Button
              variant="outline"
              onClick={() => {
                setOpen(false);
              }}
              className="mr-3"
            >
              {cancelText}
            </Button>

            <Form.Submit asChild>
              <Button className="mt-8">{confirmationText}</Button>
            </Form.Submit>
          </div>
        </Form.Root>
      </BaseModal.Content>
    </BaseModal>
  );
}
