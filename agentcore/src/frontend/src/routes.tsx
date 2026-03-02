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
import { AuthSettingsGuard } from "./components/authorization/authSettingsGuard";
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
import SettingsPage from "./pages/SettingsPage";
import ApiKeysPage from "./pages/SettingsPage/pages/ApiKeysPage";

import GlobalVariablesPage from "./pages/SettingsPage/pages/GlobalVariablesPage";
import HelpSupportPage from "./pages/SettingsPage/pages/HelpSupportPage";
import MCPServersPage from "./pages/McpServersPage";
import MessagesPage from "./pages/SettingsPage/pages/messagesPage";
import PackagesPage from "./pages/SettingsPage/pages/PackagesPage";
import ShortcutsPage from "./pages/SettingsPage/pages/ShortcutsPage";
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
import SchedulerPage from "./pages/SchedulerPage";
import useAuthStore from "./stores/authStore";

function DefaultLandingRedirect() {
  const permissions = useAuthStore((state) => state.permissions);

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

  // Scheduler is currently visible from sidebar without a permission gate.
  return <CustomNavigate replace to="scheduler" />;
}

const AdminPage = lazy(() => import("./pages/AdminPage"));
const AccessControlPage = lazy(() => import("./pages/AccessControlPage"));
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
                    path="approval"
                    element={
                      <ProtectedPermissionRoute permission="view_approval_page">
                        <ApprovalPage />
                      </ProtectedPermissionRoute>
                    }
                  />
                  <Route
                    path="approval/:agentId/review"
                    element={
                      <ProtectedPermissionRoute permission="view_approval_page">
                        <ApprovalPreviewPage />
                      </ProtectedPermissionRoute>
                    }
                  />
                  <Route
                    path="model-catalogue"
                    element={
                      
                        <ModelCatalogue />
                    
                    }
                  />
                  <Route
                    path="orchestrator-chat"
                    element={
                     
                        <AgentOrchestrator />
                
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
                        <ConnectorsCatalogueView />
                    }
                  />
                  <Route
                    path="scheduler"
                    element={<SchedulerPage />}
                  />
                  <Route
                    path="mcp-servers"
                    element={

                        <MCPServersPage />
                   
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
                      <ProtectedAccessControlRoute>
                        <TimeoutSettings />
                      </ProtectedAccessControlRoute>
                    }
                  />
                  <Route
                    path="packages"
                    element={<PackagesPage />}
                  />
                  
                  <Route
                    path="agent-catalogue"
                    element={
                    
                        <AgentCatalogueView />
                     
                    }
                  />
                  <Route
                    path="agent-catalogue/:registryId/view"
                    element={<AgentCataloguePreviewPage />}
                  />
                  <Route
                    path="observability-dashboard"
                    element={
                     
                        <ObservabilityDashboard />
               
                    }
                  />

                  <Route
                    path="workflows"
                    element={
                     
                        <WorkflowsView />
                
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
                            
                              <KnowledgePage />
                      
                          }
                        />
                      
                    </Route>
                  )}
                  <Route path="agents/">
                    <Route index element={<CollectionPage />} />
                    <Route
                      path="folder/:folderId"
                      element={<HomePage type="agents" />}
                    />
                  </Route>
                  <Route
                    path="components/"
                    element={<HomePage key="components" type="components" />}
                  >
                    <Route
                      path="folder/:folderId"
                      element={<HomePage key="components" type="components" />}
                    />
                  </Route>
                  <Route
                    path="all/"
                    element={<HomePage key="agents" type="agents" />}
                  >
                    <Route
                      path="folder/:folderId"
                      element={<HomePage key="agents" type="agents" />}
                    />
                  </Route>
                  <Route
                    path="mcp/"
                    element={<HomePage key="mcp" type="mcp" />}
                  >
                    <Route
                      path="folder/:folderId"
                      element={<HomePage key="mcp" type="mcp" />}
                    />
                  </Route>
                </Route>
                <Route
                  path="settings"
                  element={
                    
                      <SettingsPage />
                    
                  }
                >
                  <Route
                    index
                    element={<CustomNavigate replace to={"global-variables"} />}
                  />
                  <Route
                    path="global-variables"
                    element={<GlobalVariablesPage />}
                  />
                  
                  <Route path="api-keys" element={<ApiKeysPage />} />
                 
                  <Route path="shortcuts" element={<ShortcutsPage />} />
                  <Route path="messages" element={<MessagesPage />} />
                  <Route path="help-support" element={<HelpSupportPage />} />
                  {CustomRoutesStore()}
                </Route>
                <Route path="help-support" element={<HelpSupportPage />} />
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
                  path="access-control"
                  element={
                    <ProtectedAccessControlRoute>
                      <AccessControlPage />
                    </ProtectedAccessControlRoute>
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
