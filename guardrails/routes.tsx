import { lazy } from "react";
import {
  createBrowserRouter,
  createRoutesFromElements,
  Outlet,
  Route,
} from "react-router-dom";
import { ProtectedAdminRoute } from "./components/authorization/authAdminGuard";
import { ProtectedAccessControlRoute } from "./components/authorization/authAccessControlGuard";
import { ProtectedPermissionRoute } from "./components/authorization/permissionGuard";
import { ProtectedRoute } from "./components/authorization/authGuard";
import { ProtectedLoginRoute } from "./components/authorization/authLoginGuard";
import ContextWrapper from "./contexts";
import CustomDashboardWrapperPage from "./customization/components/custom-DashboardWrapperPage";
import { CustomNavigate } from "./customization/components/custom-navigate";
import { BASENAME } from "./customization/config-constants";
import {
  ENABLE_CUSTOM_PARAM,
  ENABLE_FILE_MANAGEMENT,
  ENABLE_KNOWLEDGE_BASES,
} from "./customization/feature-flags";
import { CustomRoutesStore } from "./customization/utils/custom-routes-store";
import { CustomRoutesStorePages } from "./customization/utils/custom-routes-store-pages";
import { AppAuthenticatedPage } from "./pages/AppAuthenticatedPage";
import { AppInitPage } from "./pages/AppInitPage";
import { AppWrapperPage } from "./pages/AppWrapperPage";
import AgentBuilderPage from "./pages/AgentBuilderPage";
import LoginPage from "./pages/LoginPage";
import FilesPage from "./pages/MainPage/pages/filesPage";
import HomePage from "./pages/MainPage/pages/homePage";
import KnowledgePage from "./pages/MainPage/pages/knowledgePage";

import CollectionPage from "./pages/MainPage/pages/main-page";
import HelpSupportPage from "./pages/SettingsPage/pages/HelpSupportPage";
import MCPServersPage from "./pages/McpServersPage";
import PackagesPage from "./pages/SettingsPage/pages/PackagesPage";
import ReleaseManagementPage from "./pages/ReleaseManagementPage";
import ViewPage from "./pages/ViewPage";
import ApprovalPage from "./pages/ApprovalPage";
import ApprovalPreviewPage from "./pages/ApprovalPreviewPage";
import ModelCatalogue from "./pages/ModelCatalogue";
import AgentOrchestrator from "./pages/OrchestratorChat";
import AgentCatalogueView from "./pages/AgentCatalogue";
import AgentCataloguePreviewPage from "./pages/AgentCataloguePreview";
import { Workflow } from "lucide-react";
import WorkflowsView from "./pages/WorkflowPage";
import Dashboard from "./pages/DashboardPage";
import DashboardAdmin from "./pages/DashboardPage";
import TimeoutSettings from "./pages/TimeoutSettings";
import ObservabilityDashboard from "./pages/ObservabilityPage";
import EvaluationPage from "./pages/EvaluationPage";
import GuardrailsView from "./pages/GuardrailsCatalogue";
import VectorDBView from "./pages/VectorDbPage";
import ConnectorsCatalogueView from "./pages/ConnectorsCatalogue";
import HITLApprovalsPage from "./pages/HITLApprovalsPage";
import useAuthStore from "./stores/authStore";

function DefaultLandingRedirect() {
  const permissions = useAuthStore((state) => state.permissions);
  const role = useAuthStore((state) => state.role);

  if (String(role ?? "").toLowerCase() === "root") {
    return <CustomNavigate replace to="approval" />;
  }

  if (permissions.includes("view_dashboard")) {
    return <CustomNavigate replace to="dashboard-admin" />;
  }

  if (permissions.includes("view_projects_page")) {
    return <CustomNavigate replace to="agents" />;
  }

  if (permissions.includes("view_approval_page")) {
    return <CustomNavigate replace to="approval" />;
  }

  if (permissions.includes("view_published_agents")) {
    return <CustomNavigate replace to="agent-catalogue" />;
  }

  if (permissions.includes("view_models")) {
    return <CustomNavigate replace to="model-catalogue" />;
  }

  if (permissions.includes("view_control_panel")) {
    return <CustomNavigate replace to="workflows" />;
  }

  if (permissions.includes("view_hitl_approvals_page")) {
    return <CustomNavigate replace to="hitl-approvals" />;
  }

  return <CustomNavigate replace to="dashboard-admin" />;
}

const AdminPage = lazy(() => import("./pages/AdminPage"));
const AccessControlPage = lazy(() => import("./pages/AccessControlPage"));
const CostLimitsPage = lazy(() => import("./pages/CostLimitsPage"));
const LoginAdminPage = lazy(() => import("./pages/AdminPage/LoginPage"));
const DeleteAccountPage = lazy(() => import("./pages/DeleteAccountPage"));

const PlaygroundPage = lazy(() => import("./pages/Playground"));


const router = createBrowserRouter(
  createRoutesFromElements([
    <Route path="/playground/:id/">
      <Route
        path=""
        element={
          <ContextWrapper key={1}>

              <PlaygroundPage />
            
          </ContextWrapper>
        }
      />
    </Route>,
    <Route
      path={ENABLE_CUSTOM_PARAM ? "/:customParam?" : "/"}
      element={
        <ContextWrapper key={2}>
          <Outlet />
        </ContextWrapper>
      }
    >
      <Route path="" element={<AppInitPage />}>
        <Route path="" element={<AppWrapperPage />}>
          <Route
            path=""
            element={
              <ProtectedRoute>
                <Outlet />
              </ProtectedRoute>
            }
          >
            <Route path="" element={<AppAuthenticatedPage />}>
                <Route path="" element={<CustomDashboardWrapperPage />}>
                <Route path="" element={<CollectionPage />}>
                  <Route index element={<DefaultLandingRedirect />} />
                  <Route
                    path="help-support"
                    element={
                      <ProtectedPermissionRoute permission="view_help_support_page">
                        <HelpSupportPage />
                      </ProtectedPermissionRoute>
                    }
                  />
                  <Route
                    path="approval"
                    element={
                      <ProtectedPermissionRoute permission="view_approval_page">
                        <ApprovalPage />
                      </ProtectedPermissionRoute>
                    }
                  />
                  <Route
                    path="hitl-approvals"
                    element={
                      <ProtectedPermissionRoute permission="view_hitl_approvals_page">
                        <HITLApprovalsPage />
                      </ProtectedPermissionRoute>
                    }
                  />
                  <Route
                    path="model-catalogue"
                    element={
                      <ProtectedPermissionRoute permission="view_models">
                        <ModelCatalogue />
                      </ProtectedPermissionRoute>
                    }
                  />
                  <Route
                    path="orchestrator-chat"
                    element={
                      <ProtectedPermissionRoute permission="view_orchastration_page">
                        <AgentOrchestrator />
                      </ProtectedPermissionRoute>
                    }
                  />
                  <Route
                    path="guardrails"
                    element={
                      <ProtectedPermissionRoute permission="view_guardrail_page">
                        <GuardrailsView />
                      </ProtectedPermissionRoute>
                    }
                  />
                  <Route
                    path="vector-db"
                    element={
                      <ProtectedPermissionRoute permission="view_vectordb_page">
                        <VectorDBView />
                      </ProtectedPermissionRoute>
                    }
                  />
                  <Route
                    path="connectors"
                    element={
                      <ProtectedPermissionRoute permission="view_connector_page">
                        <ConnectorsCatalogueView />
                      </ProtectedPermissionRoute>
                    }
                  />
                  <Route
                    path="mcp-servers"
                    element={
                      <ProtectedPermissionRoute permission="view_mcp_page">
                        <MCPServersPage />
                      </ProtectedPermissionRoute>
                    }
                  />
                  <Route
                    path="dashboard-admin"
                    element={
                      <ProtectedPermissionRoute permission="view_dashboard">
                        <DashboardAdmin />
                      </ProtectedPermissionRoute>
                    }
                  />
                  <Route
                    path="timeout-settings"
                    element={
                      <ProtectedPermissionRoute permission="view_platform_configs">
                        <TimeoutSettings />
                      </ProtectedPermissionRoute>
                    }
                  />
                  <Route
                    path="packages"
                    element={
                      <ProtectedPermissionRoute permission="view_packages_page">
                        <PackagesPage />
                      </ProtectedPermissionRoute>
                    }
                  />
                  <Route
                    path="release-management"
                    element={
                      <ProtectedPermissionRoute permission="view_release_management_page">
                        <ReleaseManagementPage />
                      </ProtectedPermissionRoute>
                    }
                  />
                  
                  <Route
                    path="agent-catalogue"
                    element={
                      <ProtectedPermissionRoute permission="view_published_agents">
                        <AgentCatalogueView />
                      </ProtectedPermissionRoute>
                    }
                  />
                  <Route
                    path="agent-catalogue/:registryId/view"
                    element={
                      <ProtectedPermissionRoute permission="view_published_agents">
                        <AgentCataloguePreviewPage />
                      </ProtectedPermissionRoute>
                    }
                  />
                  <Route
                    path="observability-dashboard"
                    element={
                      <ProtectedPermissionRoute permission="view_observability_page">
                        <ObservabilityDashboard />
                      </ProtectedPermissionRoute>
                    }
                  />

                  <Route
                    path="workflows"
                    element={
                      <ProtectedPermissionRoute permission="view_control_panel">
                        <WorkflowsView />
                      </ProtectedPermissionRoute>
                    }
                  />
                  <Route
                    path="evaluation"
                    element={
                      <ProtectedPermissionRoute permission="view_evaluation_page">
                        <EvaluationPage />
                      </ProtectedPermissionRoute>
                    }
                  />
                  {ENABLE_FILE_MANAGEMENT && (
                    <Route path="assets">
                      <Route
                        index
                        element={<CustomNavigate replace to="files" />}
                      />
                      <Route
                        path="files"
                        element={
                          
                            <FilesPage />
                          
                        }
                      />
                      
                        <Route
                          path="knowledge-bases"
                          element={
                            <ProtectedPermissionRoute permission="view_knowledge_base">
                              <KnowledgePage />
                            </ProtectedPermissionRoute>
                          }
                        />
                      
                    </Route>
                  )}
                  <Route
                    path="agents/"
                    element={
                      <ProtectedPermissionRoute permission="view_projects_page">
                        <Outlet />
                      </ProtectedPermissionRoute>
                    }
                  >
                    <Route index element={<CollectionPage />} />
                    <Route
                      path="folder/:folderId"
                      element={<HomePage type="agents" />}
                    />
                  </Route>
                  <Route
                    path="components/"
                    element={
                      <ProtectedPermissionRoute permission="view_projects_page">
                        <HomePage key="components" type="components" />
                      </ProtectedPermissionRoute>
                    }
                  >
                    <Route
                      path="folder/:folderId"
                      element={<HomePage key="components" type="components" />}
                    />
                  </Route>
                  <Route
                    path="all/"
                    element={
                      <ProtectedPermissionRoute permission="view_projects_page">
                        <HomePage key="agents" type="agents" />
                      </ProtectedPermissionRoute>
                    }
                  >
                    <Route
                      path="folder/:folderId"
                      element={<HomePage key="agents" type="agents" />}
                    />
                  </Route>
                  <Route
                    path="mcp/"
                    element={
                      <ProtectedPermissionRoute permission="view_projects_page">
                        <HomePage key="mcp" type="mcp" />
                      </ProtectedPermissionRoute>
                    }
                  >
                    <Route
                      path="folder/:folderId"
                      element={<HomePage key="mcp" type="mcp" />}
                    />
                  </Route>
                </Route>
                <Route
                  path="settings/*"
                  element={<CustomNavigate replace to="/" />}
                />
                {CustomRoutesStorePages()}
                <Route path="account">
                  <Route path="delete" element={<DeleteAccountPage />}></Route>
                </Route>
                <Route
                  path="admin"
                  element={
                    <ProtectedAdminRoute>
                      <AdminPage />
                    </ProtectedAdminRoute>
                  }
                />
                <Route
                  path="cost-limits"
                  element={<CostLimitsPage />}
                />
                <Route
                  path="access-control"
                  element={
                    <ProtectedAccessControlRoute>
                      <AccessControlPage />
                    </ProtectedAccessControlRoute>
                  }
                />
              </Route>
              <Route path="approval/:agentId/review" element={<CustomDashboardWrapperPage />}>
                <Route
                  path=""
                  element={
                    <ProtectedPermissionRoute permission="view_approval_page">
                      <ApprovalPreviewPage />
                    </ProtectedPermissionRoute>
                  }
                />
              </Route>
              <Route path="agent/:id/">
                <Route path="" element={<CustomDashboardWrapperPage />}>
                  <Route
                    path="folder/:folderId/"
                    element={
                     
                        <AgentBuilderPage />
                     
                    }
                  />
                  <Route
                    path=""
                    element={
                     
                        <AgentBuilderPage />
                 
                    }
                  />
                </Route>
                <Route path="view" element={<ViewPage />} />
              </Route>
            </Route>
          </Route>
          <Route
            path="login"
            element={
              <ProtectedLoginRoute>
                <LoginPage />
              </ProtectedLoginRoute>
            }
          />

          
          <Route
            path="login/admin"
            element={
              <ProtectedLoginRoute>
                <LoginAdminPage />
              </ProtectedLoginRoute>
            }
          />
        </Route>
      </Route>
      <Route path="*" element={<CustomNavigate replace to="/" />} />
    </Route>,
  ]),
  { basename: BASENAME || undefined },
);

export default router;
