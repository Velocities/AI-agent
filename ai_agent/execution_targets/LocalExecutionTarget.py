from . import ExecutionTarget

class LocalExecutionTarget(ExecutionTarget):
    def execute(self, command: str):
        """
        Execute a command locally.

        Args:
            command (str): The command to execute.
        """
        pass

    def get_local_ip(self) -> str:
        return ''