from . import ExecutionTarget

class DockerExecutionTarget(ExecutionTarget):
    def __init__(self, container_id: str):
        self.container_id = container_id

    def execute(self, command: str):
        """
        Execute a command in a Docker container.

        Args:
            command (str): The command to execute.
        """
        pass