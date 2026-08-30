from . import ExecutionTarget

class SSHExecutionTarget(ExecutionTarget):
    '''
    Represents a remote machine that can be accessed via SSH (uses SSH keys for authentication).
    '''
    def __init__(self, host: str, port: int, username: str, private_key_path: str):
        self.host = host
        self.port = port
        self.username = username
        self.private_key_path = private_key_path

    def execute(self, command: str):
        """
        Execute a command via SSH.

        Args:
            command (str): The command to execute.
        """
        pass