from abc import ABC, abstractmethod

class ExecutionTarget(ABC):
    @abstractmethod
    def execute(self, command: str):
        """
        Execute a command.

        Args:
            command (str): The command to execute. 
                TODO: Confirm the argument type before merging into the dev branch.
        """
        pass