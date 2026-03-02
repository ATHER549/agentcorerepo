from fastapi import BackgroundTasks

from agentcore.graph_langgraph import log_vertex_build
from agentcore.services.deps import get_settings_service


class LimitVertexBuildBackgroundTasks(BackgroundTasks):
    """A subclass of FastAPI BackgroundTasks that limits the number of tasks added per vertex_id.
    """

    def add_task(self, func, *args, **kwargs):
        # Only apply limiting logic to log_vertex_build tasks
        if func == log_vertex_build:
            vertex_id = kwargs.get("vertex_id")
            if vertex_id is not None:
                # Filter tasks that are log_vertex_build calls with the same vertex_id
                relevant_tasks = [
                    t for t in self.tasks if t.func == log_vertex_build and t.kwargs.get("vertex_id") == vertex_id
                ]
                if len(relevant_tasks) >= get_settings_service().settings.max_vertex_builds_per_vertex:
                    # Remove the oldest task for this vertex_id
                    oldest_task = relevant_tasks[0]
                    self.tasks.remove(oldest_task)

        super().add_task(func, *args, **kwargs)
