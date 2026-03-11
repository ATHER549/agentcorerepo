import {
  type Connection,
  type Edge,
  type NodeChange,
  type OnNodeDrag,
  type OnSelectionChangeParams,
  ReactFlow ,
  reconnectEdge,
  type SelectionDragHandler,
} from "@xyflow/react";
import _, { cloneDeep } from "lodash";
import {
  type KeyboardEvent,
  type MouseEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { useHotkeys } from "react-hotkeys-hook";
import { useShallow } from "zustand/react/shallow";
import { DefaultEdge } from "@/CustomEdges";
import NoteNode from "@/CustomNodes/NoteNode";
import AgentToolbar from "@/components/core/agentToolbarComponent";
import {
  COLOR_OPTIONS,
  NOTE_NODE_MIN_HEIGHT,
  NOTE_NODE_MIN_WIDTH,
} from "@/constants/constants";
import { useGetBuildsQuery } from "@/controllers/API/queries/_builds";
import CustomLoader from "@/customization/components/custom-loader";
import { track } from "@/customization/utils/analytics";
import useAutoSaveAgent from "@/hooks/agents/use-autosave-agent";
import useUploadAgent from "@/hooks/agents/use-upload-agent";
import { useAddComponent } from "@/hooks/use-add-component";
import { nodeColorsName } from "@/utils/styleUtils";
import { isSupportedNodeTypes } from "@/utils/utils";
import GenericNode from "../../../../CustomNodes/GenericNode";
import {
  INVALID_SELECTION_ERROR_ALERT,
  UPLOAD_ALERT_LIST,
  UPLOAD_ERROR_ALERT,
  WRONG_FILE_ERROR_ALERT,
} from "../../../../constants/alerts_constants";
import useAlertStore from "../../../../stores/alertStore";
import useAgentStore from "../../../../stores/agentStore";
import useAgentsManagerStore from "../../../../stores/agentsManagerStore";
import { useShortcutsStore } from "../../../../stores/shortcuts";
import { useTypesStore } from "../../../../stores/typesStore";
import type { APIClassType } from "../../../../types/api";
import type {
  AllNodeType,
  EdgeType,
  NoteNodeType,
} from "../../../../types/agent";
import {
  generateAgent,
  generateNodeFromAgent,
  getNodeId,
  isValidConnection,
  scapeJSONParse,
  updateIds,
  validateSelection,
} from "../../../../utils/reactFlowUtils";
import ConnectionLineComponent from "../ConnectionLineComponent";
import AgentBuildingComponent from "../agentBuildingComponent";
import SelectionMenu from "../SelectionMenuComponent";
import UpdateAllComponents from "../UpdateAllComponents";
import HelperLines from "./components/helper-lines";
import {
  getHelperLines,
  getSnapPosition,
  type HelperLinesState,
} from "./helpers/helper-lines";
import {
  MemoizedBackground,
  MemoizedCanvasControls,
  MemoizedLogCanvasControls,
  MemoizedSidebarTrigger,
} from "./MemoizedComponents";
import getRandomName from "./utils/get-random-name";
import isWrappedWithClass from "./utils/is-wrapped-with-class";

const nodeTypes = {
  genericNode: GenericNode,
  noteNode: NoteNode,
};

const edgeTypes = {
  default: DefaultEdge,
};

export default function Page({
  view,
  setIsLoading,
}: {
  view?: boolean;
  setIsLoading: (isLoading: boolean) => void;
}): JSX.Element {
  const uploadAgent = useUploadAgent();
  const autoSaveAgent = useAutoSaveAgent();
  const types = useTypesStore((state) => state.types);
  const templates = useTypesStore((state) => state.templates);
  const setFilterEdge = useAgentStore((state) => state.setFilterEdge);
  const setFilterComponent = useAgentStore((state) => state.setFilterComponent);
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const setPositionDictionary = useAgentStore(
    (state) => state.setPositionDictionary,
  );
  const reactFlowInstance = useAgentStore((state) => state.reactFlowInstance);
  const setreactFlowInstance = useAgentStore(
    (state) => state.setreactFlowInstance,
  );
  const nodes = useAgentStore((state) => state.nodes);
  const edges = useAgentStore((state) => state.edges);
  const isEmptyAgent = useRef(nodes.length === 0);
  const onNodesChange = useAgentStore((state) => state.onNodesChange);
  const onEdgesChange = useAgentStore((state) => state.onEdgesChange);
  const setNodes = useAgentStore((state) => state.setNodes);
  const setEdges = useAgentStore((state) => state.setEdges);
  const deleteNode = useAgentStore((state) => state.deleteNode);
  const deleteEdge = useAgentStore((state) => state.deleteEdge);
  const undo = useAgentsManagerStore((state) => state.undo);
  const redo = useAgentsManagerStore((state) => state.redo);
  const takeSnapshot = useAgentsManagerStore((state) => state.takeSnapshot);
  const paste = useAgentStore((state) => state.paste);
  const lastCopiedSelection = useAgentStore(
    (state) => state.lastCopiedSelection,
  );
  const setLastCopiedSelection = useAgentStore(
    (state) => state.setLastCopiedSelection,
  );
  const onConnect = useAgentStore((state) => state.onConnect);
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const updateCurrentAgent = useAgentStore((state) => state.updateCurrentAgent);
  const [selectionMenuVisible, setSelectionMenuVisible] = useState(false);
  const edgeUpdateSuccessful = useRef(true);

  const isLocked = useAgentStore(
    useShallow((state) => state.currentAgent?.locked),
  );

  const position = useRef({ x: 0, y: 0 });
  const [lastSelection, setLastSelection] =
    useState<OnSelectionChangeParams | null>(null);
  const currentAgentId = useAgentsManagerStore((state) => state.currentAgentId);

  useEffect(() => {
    if (currentAgentId !== "") {
      isEmptyAgent.current = nodes.length === 0;
    }
  }, [currentAgentId]);

  const [isAddingNote, setIsAddingNote] = useState(false);

  const addComponent = useAddComponent();

  const zoomLevel = reactFlowInstance?.getZoom();
  const shadowBoxWidth = NOTE_NODE_MIN_WIDTH * (zoomLevel || 1);
  const shadowBoxHeight = NOTE_NODE_MIN_HEIGHT * (zoomLevel || 1);
  const shadowBoxBackgroundColor = COLOR_OPTIONS[Object.keys(COLOR_OPTIONS)[0]];

  const handleGroupNode = useCallback(() => {
    takeSnapshot();
    const edgesState = useAgentStore.getState().edges;
    if (validateSelection(lastSelection!, edgesState).length === 0) {
      const clonedNodes = cloneDeep(useAgentStore.getState().nodes);
      const clonedEdges = cloneDeep(edgesState);
      const clonedSelection = cloneDeep(lastSelection);
      updateIds({ nodes: clonedNodes, edges: clonedEdges }, clonedSelection!);
      const { newAgent } = generateAgent(
        clonedSelection!,
        clonedNodes,
        clonedEdges,
        getRandomName(),
      );

      const newGroupNode = generateNodeFromAgent(newAgent, getNodeId);

      setNodes([
        ...clonedNodes.filter(
          (oldNodes) =>
            !clonedSelection?.nodes.some(
              (selectionNode) => selectionNode.id === oldNodes.id,
            ),
        ),
        newGroupNode,
      ]);
    } else {
      setErrorData({
        title: INVALID_SELECTION_ERROR_ALERT,
        list: validateSelection(lastSelection!, edgesState),
      });
    }
  }, [lastSelection, setNodes, setErrorData, takeSnapshot]);

  useEffect(() => {
    const handleMouseMove = (event) => {
      position.current = { x: event.clientX, y: event.clientY };
    };

    document.addEventListener("mousemove", handleMouseMove);

    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
    };
  }, [lastCopiedSelection, lastSelection, takeSnapshot, selectionMenuVisible]);

  const { isFetching } = useGetBuildsQuery({ agentId: currentAgentId });

  const showCanvas =
    Object.keys(templates).length > 0 &&
    Object.keys(types).length > 0 &&
    !isFetching;

  useEffect(() => {
    setIsLoading(!showCanvas);
  }, [showCanvas]);

  useEffect(() => {
    useAgentStore.setState({ autoSaveAgent });
  }, [autoSaveAgent]);

  function handleUndo(e: KeyboardEvent) {
    if (!isWrappedWithClass(e, "noflow")) {
      e.preventDefault();
      (e as unknown as Event).stopImmediatePropagation();
      undo();
    }
  }

  function handleRedo(e: KeyboardEvent) {
    if (!isWrappedWithClass(e, "noflow")) {
      e.preventDefault();
      (e as unknown as Event).stopImmediatePropagation();
      redo();
    }
  }

  function handleGroup(e: KeyboardEvent) {
    if (selectionMenuVisible) {
      e.preventDefault();
      (e as unknown as Event).stopImmediatePropagation();
      handleGroupNode();
    }
  }

  function handleDuplicate(e: KeyboardEvent) {
    e.preventDefault();
    e.stopPropagation();
    (e as unknown as Event).stopImmediatePropagation();
    const selectedNode = nodes.filter((obj) => obj.selected);
    if (selectedNode.length > 0) {
      paste(
        { nodes: selectedNode, edges: [] },
        {
          x: position.current.x,
          y: position.current.y,
        },
      );
    }
  }

  function handleCopy(e: KeyboardEvent) {
    const multipleSelection = lastSelection?.nodes
      ? lastSelection?.nodes.length > 0
      : false;
    const hasTextSelection =
      (window.getSelection()?.toString().length ?? 0) > 0;

    if (
      !isWrappedWithClass(e, "noflow") &&
      !hasTextSelection &&
      (isWrappedWithClass(e, "react-flow__node") || multipleSelection)
    ) {
      e.preventDefault();
      (e as unknown as Event).stopImmediatePropagation();
      if (lastSelection) {
        setLastCopiedSelection(_.cloneDeep(lastSelection));
      }
    }
  }

  function handleCut(e: KeyboardEvent) {
    if (!isWrappedWithClass(e, "noflow")) {
      e.preventDefault();
      (e as unknown as Event).stopImmediatePropagation();
      if (window.getSelection()?.toString().length === 0 && lastSelection) {
        setLastCopiedSelection(_.cloneDeep(lastSelection), true);
      }
    }
  }

  function handlePaste(e: KeyboardEvent) {
    if (!isWrappedWithClass(e, "noflow")) {
      e.preventDefault();
      (e as unknown as Event).stopImmediatePropagation();
      if (
        window.getSelection()?.toString().length === 0 &&
        lastCopiedSelection
      ) {
        takeSnapshot();
        paste(lastCopiedSelection, {
          x: position.current.x,
          y: position.current.y,
        });
      }
    }
  }

  function handleDelete(e: KeyboardEvent) {
    if (isLocked) return;
    if (!isWrappedWithClass(e, "nodelete") && lastSelection) {
      e.preventDefault();
      (e as unknown as Event).stopImmediatePropagation();
      takeSnapshot();
      if (lastSelection.edges?.length) {
        track("Component Connection Deleted");
      }
      if (lastSelection.nodes?.length) {
        lastSelection.nodes.forEach((n) => {
          track("Component Deleted", { componentType: n.data.type });
        });
      }
      deleteNode(lastSelection.nodes.map((node) => node.id));
      deleteEdge(lastSelection.edges.map((edge) => edge.id));
    }
  }

  const undoAction = useShortcutsStore((state) => state.undo);
  const redoAction = useShortcutsStore((state) => state.redo);
  const redoAltAction = useShortcutsStore((state) => state.redoAlt);
  const copyAction = useShortcutsStore((state) => state.copy);
  const duplicate = useShortcutsStore((state) => state.duplicate);
  const deleteAction = useShortcutsStore((state) => state.delete);
  const groupAction = useShortcutsStore((state) => state.group);
  const cutAction = useShortcutsStore((state) => state.cut);
  const pasteAction = useShortcutsStore((state) => state.paste);
  //@ts-ignore
  useHotkeys(undoAction, handleUndo);
  //@ts-ignore
  useHotkeys(redoAction, handleRedo);
  //@ts-ignore
  useHotkeys(redoAltAction, handleRedo);
  //@ts-ignore
  useHotkeys(groupAction, handleGroup);
  //@ts-ignore
  useHotkeys(duplicate, handleDuplicate);
  //@ts-ignore
  useHotkeys(copyAction, handleCopy);
  //@ts-ignore
  useHotkeys(cutAction, handleCut);
  //@ts-ignore
  useHotkeys(pasteAction, handlePaste);
  //@ts-ignore
  useHotkeys(deleteAction, handleDelete);
  //@ts-ignore
  useHotkeys("delete", handleDelete);

  const onConnectMod = useCallback(
    (params: Connection) => {
      takeSnapshot();
      onConnect(params);
      track("New Component Connection Added");
    },
    [takeSnapshot, onConnect],
  );

  const [helperLines, setHelperLines] = useState<HelperLinesState>({});
  const [isDragging, setIsDragging] = useState(false);
  const helperLineEnabled = useAgentStore((state) => state.helperLineEnabled);

  const onNodeDrag: OnNodeDrag = useCallback(
    (_, node) => {
      if (helperLineEnabled) {
        const currentHelperLines = getHelperLines(node, nodes);
        setHelperLines(currentHelperLines);
      }
    },
    [helperLineEnabled, nodes],
  );

  const onNodeDragStart: OnNodeDrag = useCallback(
    (_, node) => {
      // 👇 make dragging a node undoable
      takeSnapshot();
      setIsDragging(true);
      // 👉 you can place your event handlers here
    },
    [takeSnapshot],
  );

  const onNodeDragStop: OnNodeDrag = useCallback(
    (_, node) => {
      // 👇 make moving the canvas undoable
      autoSaveAgent();
      updateCurrentAgent({ nodes });
      setPositionDictionary({});
      setIsDragging(false);
      setHelperLines({});
    },
    [
      takeSnapshot,
      autoSaveAgent,
      nodes,
      edges,
      reactFlowInstance,
      setPositionDictionary,
    ],
  );

  const onNodesChangeWithHelperLines = useCallback(
    (changes: NodeChange<AllNodeType>[]) => {
      if (!helperLineEnabled) {
        onNodesChange(changes);
        return;
      }

      // Apply snapping to position changes during drag
      const modifiedChanges = changes.map((change) => {
        if (
          change.type === "position" &&
          "dragging" in change &&
          "position" in change &&
          "id" in change &&
          isDragging
        ) {
          const nodeId = change.id as string;
          const draggedNode = nodes.find((n) => n.id === nodeId);

          if (draggedNode && change.position) {
            const updatedNode = {
              ...draggedNode,
              position: change.position,
            };

            const snapPosition = getSnapPosition(updatedNode, nodes);

            // Only snap if we're actively dragging
            if (change.dragging) {
              // Apply snap if there's a significant difference
              if (
                Math.abs(snapPosition.x - change.position.x) > 0.1 ||
                Math.abs(snapPosition.y - change.position.y) > 0.1
              ) {
                return {
                  ...change,
                  position: snapPosition,
                };
              }
            } else {
              // This is the final position change when drag ends
              // Force snap to ensure it stays where it should
              return {
                ...change,
                position: snapPosition,
              };
            }
          }
        }
        return change;
      });

      onNodesChange(modifiedChanges);
    },
    [onNodesChange, nodes, isDragging, helperLineEnabled],
  );

  const onSelectionDragStart: SelectionDragHandler = useCallback(() => {
    takeSnapshot();
  }, [takeSnapshot]);

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    if (event.dataTransfer.types.some((types) => isSupportedNodeTypes(types))) {
      event.dataTransfer.dropEffect = "move";
    } else {
      event.dataTransfer.dropEffect = "copy";
    }
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      if (isLocked) return;
      const grabbingElement =
        document.getElementsByClassName("cursor-grabbing");
      if (grabbingElement.length > 0) {
        document.body.removeChild(grabbingElement[0]);
      }
      if (event.dataTransfer.types.some((type) => isSupportedNodeTypes(type))) {
        takeSnapshot();

        const datakey = event.dataTransfer.types.find((type) =>
          isSupportedNodeTypes(type),
        );

        // Extract the data from the drag event and parse it as a JSON object
        const data: { type: string; node?: APIClassType } = JSON.parse(
          event.dataTransfer.getData(datakey!),
        );

        addComponent(data.node!, data.type, {
          x: event.clientX,
          y: event.clientY,
        });
      } else if (event.dataTransfer.types.some((types) => types === "Files")) {
        takeSnapshot();
        const position = {
          x: event.clientX,
          y: event.clientY,
        };
        uploadAgent({
          files: Array.from(event.dataTransfer.files!),
          position: position,
        }).catch((error) => {
          setErrorData({
            title: UPLOAD_ERROR_ALERT,
            list: [(error as Error).message],
          });
        });
      } else {
        setErrorData({
          title: WRONG_FILE_ERROR_ALERT,
          list: [UPLOAD_ALERT_LIST],
        });
      }
    },
    [takeSnapshot, addComponent],
  );

  const onEdgeUpdateStart = useCallback(() => {
    edgeUpdateSuccessful.current = false;
  }, []);

  const onEdgeUpdate = useCallback(
    (oldEdge: EdgeType, newConnection: Connection) => {
      if (isValidConnection(newConnection, nodes, edges)) {
        edgeUpdateSuccessful.current = true;
        oldEdge.data = {
          targetHandle: scapeJSONParse(newConnection.targetHandle!),
          sourceHandle: scapeJSONParse(newConnection.sourceHandle!),
        };
        setEdges((els) => reconnectEdge(oldEdge, newConnection, els));
      }
    },
    [setEdges],
  );

  const onEdgeUpdateEnd = useCallback((_, edge: Edge): void => {
    if (!edgeUpdateSuccessful.current) {
      setEdges((eds) => eds.filter((edg) => edg.id !== edge.id));
    }
    edgeUpdateSuccessful.current = true;
  }, []);

  const [selectionEnded, setSelectionEnded] = useState(true);

  const onSelectionEnd = useCallback(() => {
    setSelectionEnded(true);
  }, []);
  const onSelectionStart = useCallback((event: MouseEvent) => {
    event.preventDefault();
    setSelectionEnded(false);
  }, []);

  // Workaround to show the menu only after the selection has ended.
  useEffect(() => {
    if (selectionEnded && lastSelection && lastSelection.nodes.length > 1) {
      setSelectionMenuVisible(true);
    } else {
      setSelectionMenuVisible(false);
    }
  }, [selectionEnded, lastSelection]);

  const onSelectionChange = useCallback(
    (agent: OnSelectionChangeParams): void => {
      setLastSelection(agent);
    },
    [],
  );

  const onPaneClick = useCallback(
    (event: React.MouseEvent) => {
      setFilterEdge([]);
      setFilterComponent("");
      if (isAddingNote) {
        const shadowBox = document.getElementById("shadow-box");
        if (shadowBox) {
          shadowBox.style.display = "none";
        }
        const position = reactFlowInstance?.screenToAgentPosition({
          x: event.clientX - shadowBoxWidth / 2,
          y: event.clientY - shadowBoxHeight / 2,
        });
        const data = {
          node: {
            description: "",
            display_name: "",
            documentation: "",
            template: {},
          },
          type: "note",
        };
        const newId = getNodeId(data.type);

        const newNode: NoteNodeType = {
          id: newId,
          type: "noteNode",
          position: position || { x: 0, y: 0 },
          data: {
            ...data,
            id: newId,
          },
        };
        setNodes((nds) => nds.concat(newNode));
        setIsAddingNote(false);
        // Signal sidebar to revert add_note active state
        window.dispatchEvent(new Event("lf:end-add-note"));
      }
    },
    [
      isAddingNote,
      setNodes,
      reactFlowInstance,
      getNodeId,
      setFilterEdge,
      setFilterComponent,
    ],
  );

  const handleEdgeClick = (event, edge) => {
    if (isLocked) {
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    const color =
      nodeColorsName[edge?.data?.sourceHandle?.output_types[0]] || "cyan";

    const accentColor = `hsl(var(--datatype-${color}))`;
    reactFlowWrapper.current?.style.setProperty("--selected", accentColor);
  };

  const handleKeyDown = (e: KeyboardEvent) => {
    if (isLocked) {
      e.preventDefault();
      e.stopPropagation();
    }
  };

  useEffect(() => {
    const handleGlobalMouseMove = (event) => {
      if (isAddingNote) {
        const shadowBox = document.getElementById("shadow-box");
        if (shadowBox) {
          shadowBox.style.display = "block";
          shadowBox.style.left = `${event.clientX - shadowBoxWidth / 2}px`;
          shadowBox.style.top = `${event.clientY - shadowBoxHeight / 2}px`;
        }
      }
    };

    document.addEventListener("mousemove", handleGlobalMouseMove);

    return () => {
      document.removeEventListener("mousemove", handleGlobalMouseMove);
    };
  }, [isAddingNote, shadowBoxWidth, shadowBoxHeight]);

  // Listen for a global event to start the add-note agent from outside components
  useEffect(() => {
    const handleStartAddNote = () => {
      setIsAddingNote(true);
      const shadowBox = document.getElementById("shadow-box");
      if (shadowBox) {
        shadowBox.style.display = "block";
        shadowBox.style.left = `${position.current.x - shadowBoxWidth / 2}px`;
        shadowBox.style.top = `${position.current.y - shadowBoxHeight / 2}px`;
      }
    };

    window.addEventListener("lf:start-add-note", handleStartAddNote);
    return () => {
      window.removeEventListener("lf:start-add-note", handleStartAddNote);
    };
  }, [shadowBoxWidth, shadowBoxHeight]);

  const MIN_ZOOM = 0.25;
  const MAX_ZOOM = 2;
  const fitViewOptions = {
    minZoom: MIN_ZOOM,
    maxZoom: MAX_ZOOM,
  };

  return (
    <div className="h-full w-full bg-canvas" ref={reactFlowWrapper}>
      {showCanvas ? (
        <>
          <div id="react-flow-id" className="h-full w-full bg-canvas relative">
            {!view && (
              <>
                <MemoizedLogCanvasControls />
                <MemoizedCanvasControls
                  setIsAddingNote={setIsAddingNote}
                  shadowBoxWidth={shadowBoxWidth}
                  shadowBoxHeight={shadowBoxHeight}
                />
                <AgentToolbar />
              </>
            )}
            <MemoizedSidebarTrigger />
            <SelectionMenu
              lastSelection={lastSelection}
              isVisible={selectionMenuVisible}
              nodes={lastSelection?.nodes}
              onClick={handleGroupNode}
            />
            <ReactFlow<AllNodeType, EdgeType>
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChangeWithHelperLines}
              onEdgesChange={onEdgesChange}
              onConnect={isLocked ? undefined : onConnectMod}
              disableKeyboardA11y={true}
              nodesFocusable={!isLocked}
              edgesFocusable={!isLocked}
              onInit={setreactFlowInstance}
              nodeTypes={nodeTypes}
              onReconnect={isLocked ? undefined : onEdgeUpdate}
              onReconnectStart={isLocked ? undefined : onEdgeUpdateStart}
              onReconnectEnd={isLocked ? undefined : onEdgeUpdateEnd}
              onNodeDrag={onNodeDrag}
              onNodeDragStart={onNodeDragStart}
              onSelectionDragStart={onSelectionDragStart}
              elevateEdgesOnSelect={false}
              onSelectionEnd={onSelectionEnd}
              onSelectionStart={onSelectionStart}
              connectionRadius={30}
              edgeTypes={edgeTypes}
              connectionLineComponent={ConnectionLineComponent}
              onDragOver={onDragOver}
              onNodeDragStop={onNodeDragStop}
              onDrop={onDrop}
              onSelectionChange={onSelectionChange}
              deleteKeyCode={[]}
              fitView={isEmptyAgent.current ? false : true}
              fitViewOptions={fitViewOptions}
              className="theme-attribution"
              tabIndex={isLocked ? -1 : undefined}
              minZoom={MIN_ZOOM}
              maxZoom={MAX_ZOOM}
              zoomOnScroll={!view}
              zoomOnPinch={!view}
              panOnDrag={!view}
              panActivationKeyCode={""}
              proOptions={{ hideAttribution: true }}
              onPaneClick={onPaneClick}
              onEdgeClick={handleEdgeClick}
              onKeyDown={handleKeyDown}
            >
              <AgentBuildingComponent />
              <UpdateAllComponents />
              <MemoizedBackground />
              {helperLineEnabled && <HelperLines helperLines={helperLines} />}
            </ReactFlow>
          </div>
          <div
            id="shadow-box"
            style={{
              position: "absolute",
              width: `${shadowBoxWidth}px`,
              height: `${shadowBoxHeight}px`,
              backgroundColor: `${shadowBoxBackgroundColor}`,
              opacity: 0.7,
              pointerEvents: "none",
              // Prevent shadow-box from showing unexpectedly during initial renders
              display: "none",
            }}
          ></div>
        </>
      ) : (
        <div className="flex h-full w-full items-center justify-center">
          <CustomLoader remSize={30} />
        </div>
      )}
    </div>
  );
}
