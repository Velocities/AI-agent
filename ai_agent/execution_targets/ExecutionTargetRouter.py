from . import ExecutionTarget

class ExecutionTargetRouter:
    '''
    Routes commands to the appropriate execution target chosen by the user via a dictionary lookup
    (it's easier to use human-readable names than IP addresses or container IDs).
    '''
    def __init__(self, default_execution_target: ExecutionTarget):
        self.default_execution_target = default_execution_target
        self.execution_targets = dict[str, ExecutionTarget]()
    
    def add_execution_target(self, name: str, execution_target: ExecutionTarget):
        self.execution_targets[name] = execution_target

    def get_execution_target(self, name: str) -> ExecutionTarget:
        return self.execution_targets[name]

    def remove_execution_target(self, name: str):
        del self.execution_targets[name]

    def get_all_execution_targets(self) -> dict[str, ExecutionTarget]:
        return self.execution_targets