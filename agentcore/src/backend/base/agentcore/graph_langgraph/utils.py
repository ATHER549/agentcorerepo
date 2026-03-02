
from __future__ import annotations

import copy
from collections import defaultdict, deque
from typing import Any


def process_agent(agent_object: dict[str, Any]) -> dict[str, Any]:
    """Process agent data to handle group nodes.
    
    This is a simplified version that handles nested agents.
    
    Args:
        agent_object: Agent data with nodes and edges
        
    Returns:
        Processed agent data
    """
    cloned_agent = copy.deepcopy(agent_object)
    processed_nodes = set()
    
    def process_node(node: dict[str, Any]) -> None:
        node_id = node.get("id")
        
        if node_id in processed_nodes:
            return
        
        # Check if node contains a nested agent
        if (node.get("data") and 
            node["data"].get("node") and 
            node["data"]["node"].get("agent")):
            # Recursively process nested agent
            process_agent(node["data"]["node"]["agent"]["data"])
        
        processed_nodes.add(node_id)
    
    nodes_to_process = deque(cloned_agent.get("nodes", []))
    
    while nodes_to_process:
        node = nodes_to_process.popleft()
        process_node(node)
    
    return cloned_agent


def has_cycle(vertex_ids: list[str], edges: list[tuple[str, str]]) -> bool:
    """Check if graph contains cycles.
    
    Args:
        vertex_ids: List of vertex IDs
        edges: List of (source, target) edge tuples
        
    Returns:
        True if graph has cycles
    """
    # Build adjacency list
    graph = defaultdict(list)
    for source, target in edges:
        graph[source].append(target)
    
    # DFS to detect cycle
    def dfs(vertex: str, visited: set[str], rec_stack: set[str]) -> bool:
        visited.add(vertex)
        rec_stack.add(vertex)
        
        for neighbor in graph[vertex]:
            if neighbor not in visited:
                if dfs(neighbor, visited, rec_stack):
                    return True
            elif neighbor in rec_stack:
                return True
        
        rec_stack.remove(vertex)
        return False
    
    visited: set[str] = set()
    rec_stack: set[str] = set()
    
    for vertex in vertex_ids:
        if vertex not in visited:
            if dfs(vertex, visited, rec_stack):
                return True
    
    return False


def find_cycle_vertices(edges: list[tuple[str, str]]) -> list[str]:
    """Find vertices that are part of cycles.
    
    Args:
        edges: List of (source, target) edge tuples
        
    Returns:
        List of vertex IDs in cycles
    """
    # Build adjacency list
    graph = defaultdict(list)
    for source, target in edges:
        graph[source].append(target)
    
    cycle_vertices = set()
    
    def dfs(vertex: str, visited: set[str], rec_stack: set[str], path: list[str]) -> None:
        visited.add(vertex)
        rec_stack.add(vertex)
        path.append(vertex)
        
        for neighbor in graph[vertex]:
            if neighbor not in visited:
                dfs(neighbor, visited, rec_stack, path)
            elif neighbor in rec_stack:
                # Found a cycle - add all vertices in the cycle
                cycle_start_idx = path.index(neighbor)
                cycle_vertices.update(path[cycle_start_idx:])
        
        rec_stack.remove(vertex)
        path.pop()
    
    visited: set[str] = set()
    rec_stack: set[str] = set()
    
    #for vertex in graph:
    for vertex in list(graph):
        if vertex not in visited:
            dfs(vertex, visited, rec_stack, [])
    
    return sorted(cycle_vertices)


def build_adjacency_maps(
    edges_data: list[dict[str, Any]]
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Build predecessor and successor maps from edges.
    
    Args:
        edges_data: List of edge data dictionaries
        
    Returns:
        Tuple of (predecessor_map, successor_map)
    """
    predecessor_map: dict[str, set[str]] = defaultdict(set)
    successor_map: dict[str, set[str]] = defaultdict(set)
    
    for edge in edges_data:
        source_id = edge.get("source")
        target_id = edge.get("target")
        
        if source_id and target_id:
            predecessor_map[target_id].add(source_id)
            successor_map[source_id].add(target_id)
    
    # Convert sets to lists for consistency
    return {k: list(v) for k, v in predecessor_map.items()}, {k: list(v) for k, v in successor_map.items()}


def build_in_degree_map(
    edges_data: list[dict[str, Any]], 
    all_vertex_ids: set[str]
) -> dict[str, int]:
    """Build in-degree map for vertices.
    
    Args:
        edges_data: List of edge data
        all_vertex_ids: Set of all vertex IDs
        
    Returns:
        Dictionary mapping vertex ID to its in-degree
    """
    in_degree: dict[str, int] = {vid: 0 for vid in all_vertex_ids}
    
    for edge in edges_data:
        target_id = edge.get("target")
        if target_id and target_id in in_degree:
            in_degree[target_id] += 1
    
    return in_degree


def filter_vertices_up_to_vertex(
    vertices_ids: list[str],
    stop_vertex_id: str,
    predecessor_map: dict[str, list[str]],
) -> set[str]:
    """Filter vertices to only include those that lead up to (are predecessors of) the stop vertex.
    
    This function performs a breadth-first traversal backwards from the stop vertex,
    collecting all vertices that are predecessors (directly or indirectly) of the stop vertex.
    This is used for "Run Till Specific Component" functionality.
    
    Args:
        vertices_ids: List of all vertex IDs in the graph
        stop_vertex_id: ID of the vertex to stop at (will be included in result)
        predecessor_map: Map of vertex ID -> list of predecessor vertex IDs
        
    Returns:
        Set of vertex IDs that lead to the stop vertex (including the stop vertex itself)
        
    Example:
        Given graph: A -> B -> C -> D
        If stop_vertex_id = "C", returns {"A", "B", "C"}
        
        Given graph: 
            A -> C
            B -> C -> D
        If stop_vertex_id = "C", returns {"A", "B", "C"}
    """
    vertices_set = set(vertices_ids)
    
    # If stop vertex doesn't exist, return empty
    if stop_vertex_id not in vertices_set:
        return set()
    
    # Start with the target vertex
    filtered_vertices = {stop_vertex_id}
    queue = deque([stop_vertex_id])
    
    # Process vertices in breadth-first order going backwards
    while queue:
        current_vertex = queue.popleft()
        predecessors = predecessor_map.get(current_vertex, [])
        
        for predecessor in predecessors:
            if predecessor in vertices_set and predecessor not in filtered_vertices:
                filtered_vertices.add(predecessor)
                queue.append(predecessor)
    
    return filtered_vertices


def filter_vertices_from_vertex(
    vertices_ids: list[str],
    start_vertex_id: str,
    successor_map: dict[str, list[str]],
) -> set[str]:
    """Filter vertices to only include those reachable from the start vertex.
    
    This function performs a breadth-first traversal forward from the start vertex,
    collecting all vertices that are successors (directly or indirectly) of the start vertex.
    This is used for "Run From Specific Component" functionality.
    
    Args:
        vertices_ids: List of all vertex IDs in the graph
        start_vertex_id: ID of the vertex to start from (will be included in result)
        successor_map: Map of vertex ID -> list of successor vertex IDs
        
    Returns:
        Set of vertex IDs reachable from the start vertex (including the start vertex itself)
        
    Example:
        Given graph: A -> B -> C -> D
        If start_vertex_id = "B", returns {"B", "C", "D"}
    """
    vertices_set = set(vertices_ids)
    
    # If start vertex doesn't exist, return empty
    if start_vertex_id not in vertices_set:
        return set()
    
    # Start with the start vertex
    filtered_vertices = {start_vertex_id}
    queue = deque([start_vertex_id])
    
    # Process vertices in breadth-first order going forward
    while queue:
        current_vertex = queue.popleft()
        successors = successor_map.get(current_vertex, [])
        
        for successor in successors:
            if successor in vertices_set and successor not in filtered_vertices:
                filtered_vertices.add(successor)
                queue.append(successor)
    
    return filtered_vertices


def get_sorted_vertices_for_langgraph(
    vertices_ids: list[str],
    in_degree_map: dict[str, int],
    predecessor_map: dict[str, list[str]],
    successor_map: dict[str, list[str]],
    cycle_vertices: set[str],
    stop_component_id: str | None = None,
    start_component_id: str | None = None,
    is_cyclic: bool = False,
) -> tuple[list[str], list[str], set[str]]:
    """Get sorted vertices for LangGraph execution, handling stop/start components.
    
    This function:
    1. Filters vertices based on stop_component_id (only predecessors)
    2. Filters vertices based on start_component_id (only successors)
    3. Returns first layer (vertices with no dependencies) and all vertices to run
    
    Args:
        vertices_ids: All vertex IDs in the graph
        in_degree_map: Map of vertex ID to number of incoming edges
        predecessor_map: Map of vertex ID to list of predecessor IDs
        successor_map: Map of vertex ID to list of successor IDs
        cycle_vertices: Set of vertex IDs that are part of cycles
        stop_component_id: Optional ID of component to stop at
        start_component_id: Optional ID of component to start from
        is_cyclic: Whether the graph contains cycles
        
    Returns:
        Tuple of (first_layer_vertices, all_vertices_to_run, filtered_vertices_set)
    """
    working_vertices = set(vertices_ids)
    
    # Handle cycle case: if stop component is in a cycle, convert to start
    if stop_component_id and stop_component_id in cycle_vertices:
        start_component_id = stop_component_id
        stop_component_id = None
    
    # Filter vertices up to stop component (only predecessors)
    if stop_component_id is not None:
        filtered = filter_vertices_up_to_vertex(
            list(working_vertices),
            stop_component_id,
            predecessor_map,
        )
        working_vertices = filtered
    
    # Filter vertices from start component (only successors + their predecessors)
    if start_component_id is not None:
        # Get all vertices reachable from start
        reachable = filter_vertices_from_vertex(
            list(working_vertices),
            start_component_id,
            successor_map,
        )
        # Also include predecessors of reachable vertices
        connected_vertices = set()
        for vertex in reachable:
            predecessors_of_vertex = filter_vertices_up_to_vertex(
                list(working_vertices),
                vertex,
                predecessor_map,
            )
            connected_vertices.update(predecessors_of_vertex)
        working_vertices = connected_vertices
    
    # Build filtered in_degree_map for the working vertices
    filtered_in_degree = {}
    for vid in working_vertices:
        # Count only predecessors that are in working_vertices
        preds = predecessor_map.get(vid, [])
        filtered_preds = [p for p in preds if p in working_vertices]
        filtered_in_degree[vid] = len(filtered_preds)
    
    # First layer: vertices with no dependencies (in_degree == 0) within filtered set
    first_layer = [vid for vid, degree in filtered_in_degree.items() if degree == 0]
    
    # All vertices to run
    vertices_to_run = list(working_vertices)
    
    return first_layer, vertices_to_run, working_vertices


def has_chat_output(vertices: dict[Any, int]) -> bool:
    """Check if any vertex has ChatOutput in its ID.
    
    Args:
        vertices: Dictionary mapping vertices to their counts/indices
        
    Returns:
        True if any vertex has ChatOutput in its ID
    """
    from agentcore.graph_langgraph.schema import InterfaceComponentTypes

    return any(InterfaceComponentTypes.ChatOutput in vertex.id for vertex in vertices)


def has_output_vertex(vertices: dict[Any, int]) -> bool:
    """Check if any vertex is an output vertex.
    
    Args:
        vertices: Dictionary mapping vertices to their counts/indices
        
    Returns:
        True if any vertex is an output vertex
    """
    return any(vertex.is_output for vertex in vertices)


PRIORITY_LIST_OF_INPUTS = ["webhook", "chat"]
MAX_CYCLE_APPEARANCES = 2


def find_start_component_id(vertices, *, is_webhook: bool = False):
    """Finds the component ID from a list of vertices based on a priority list of input types.

    Args:
        vertices (list): A list of vertex IDs.
        is_webhook (bool, optional): Whether the agent is being run as a webhook. Defaults to False.

    Returns:
        str or None: The component ID that matches the highest priority input type, or None if no match is found.
    """
    priority_inputs = ["webhook"] if is_webhook else PRIORITY_LIST_OF_INPUTS
    for input_type_str in priority_inputs:
        component_id = next((vertex_id for vertex_id in vertices if input_type_str in vertex_id.lower()), None)
        if component_id:
            return component_id
    return None


def layered_topological_sort(
    vertices_ids: set[str],
    in_degree_map: dict[str, int],
    successor_map: dict[str, list[str]],
    predecessor_map: dict[str, list[str]],
    start_id: str | None = None,
    cycle_vertices: set[str] | None = None,
    is_input_vertex: Any | None = None,
    *,
    is_cyclic: bool = False,
) -> list[list[str]]:
    """Performs a layered topological sort of the vertices in the graph.

    Args:
        vertices_ids: Set of vertex IDs to sort
        in_degree_map: Map of vertex IDs to their in-degree
        successor_map: Map of vertex IDs to their successors
        predecessor_map: Map of vertex IDs to their predecessors
        is_cyclic: Whether the graph is cyclic
        start_id: ID of the start vertex (if any)
        cycle_vertices: Set of vertices that form a cycle
        is_input_vertex: Function to check if a vertex is an input vertex (unused)

    Returns:
        List of layers, where each layer is a list of vertex IDs
    """
    _ = is_input_vertex  # Unused parameter kept for API compatibility
    cycle_vertices = cycle_vertices or set()
    in_degree_map = in_degree_map.copy()

    if is_cyclic and all(in_degree_map.values()):
        if start_id is not None:
            queue = deque([start_id])
            in_degree_map[start_id] = 0
        else:
            chat_input = find_start_component_id(vertices_ids)
            if chat_input is None:
                queue = deque([next(iter(vertices_ids))])
                in_degree_map[next(iter(vertices_ids))] = 0
            else:
                queue = deque([chat_input])
                in_degree_map[chat_input] = 0
    else:
        queue = deque(
            vertex_id
            for vertex_id in vertices_ids
            if in_degree_map[vertex_id] == 0
        )

    layers: list[list[str]] = []
    visited = set()
    cycle_counts = dict.fromkeys(vertices_ids, 0)
    current_layer = 0

    if queue:
        layers.append([])
        first_layer_vertices = set()
        layer_size = len(queue)
        for _ in range(layer_size):
            vertex_id = queue.popleft()
            if vertex_id not in first_layer_vertices:
                first_layer_vertices.add(vertex_id)
                visited.add(vertex_id)
                cycle_counts[vertex_id] += 1
                layers[current_layer].append(vertex_id)

            for neighbor in successor_map[vertex_id]:
                if neighbor not in vertices_ids:
                    continue

                in_degree_map[neighbor] -= 1
                if in_degree_map[neighbor] == 0:
                    queue.append(neighbor)
                elif in_degree_map[neighbor] > 0:
                    for predecessor in predecessor_map[neighbor]:
                        if (
                            predecessor not in queue
                            and predecessor not in first_layer_vertices
                            and (in_degree_map[predecessor] == 0 or predecessor in cycle_vertices)
                        ):
                            queue.append(predecessor)

        current_layer += 1

    while queue:
        layers.append([])
        layer_size = len(queue)
        for _ in range(layer_size):
            vertex_id = queue.popleft()
            if vertex_id not in visited or (is_cyclic and cycle_counts[vertex_id] < MAX_CYCLE_APPEARANCES):
                if vertex_id not in visited:
                    visited.add(vertex_id)
                cycle_counts[vertex_id] += 1
                layers[current_layer].append(vertex_id)

            for neighbor in successor_map[vertex_id]:
                if neighbor not in vertices_ids:
                    continue

                in_degree_map[neighbor] -= 1
                if in_degree_map[neighbor] == 0 and neighbor not in visited:
                    queue.append(neighbor)
                elif in_degree_map[neighbor] > 0:
                    for predecessor in predecessor_map[neighbor]:
                        if predecessor not in queue and (
                            predecessor not in visited
                            or (is_cyclic and cycle_counts[predecessor] < MAX_CYCLE_APPEARANCES)
                        ):
                            queue.append(predecessor)

        current_layer += 1

    return [layer for layer in layers if layer]
