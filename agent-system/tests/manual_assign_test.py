"""
Manual test: verify in-process A2A routing delivers assignment to WorkerAgent
and the worker adds the task to its local state and executes it. This test
does not require Redis.
"""
from core.a2a_messaging import A2ARouter, GLOBAL_A2A_ROUTER
from core.a2a_messaging import A2AConfig, A2AClient, MessageType
from worker.agent import WorkerAgent
from core.langgraph_state import Task


def run_manual():
    router = A2ARouter()

    # Wire router into module
    import core.a2a_messaging as _a2a_mod
    _a2a_mod.GLOBAL_A2A_ROUTER = router

    # Create a worker (doesn't initialize Redis)
    worker = WorkerAgent(agent_id="worker-1", distributor_id="distributor-1", a2a_config=A2AConfig(agent_id="worker-1", token_secret="s"))

    # Register worker client in router
    router.register_agent("worker-1", worker.a2a_client)

    # Create a fake distributor A2A client to build the message
    dist_client = A2AClient(A2AConfig(agent_id="distributor-1", token_secret="s"))

    task = Task(task_id="task-1", task_type="compute", payload={})
    message = dist_client.create_message("worker-1", {"action": "assign_task", "task": task.to_dict()}, MessageType.REQUEST)

    print("Before assignment: pending:", [t.task_id for t in worker.local_state.local_tasks])

    # Deliver message via router (simulates distributor sending assignment)
    router.route_message(message)

    print("After assignment: local_tasks:", [t.task_id for t in worker.local_state.local_tasks])
    completed = [t for t in worker.local_state.local_tasks if t.status.value == "completed"]
    print("Completed count:", len(completed))


if __name__ == '__main__':
    run_manual()
