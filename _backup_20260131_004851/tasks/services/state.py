from core.constants import TaskStatus, TaskCategory

class TaskStateService:
    """
    Service to handle task state transitions and validation.
    """
    
    BUG_FLOW = {
        TaskStatus.NEW: [TaskStatus.CONFIRMED],
        TaskStatus.CONFIRMED: [TaskStatus.FIXING],
        TaskStatus.FIXING: [TaskStatus.VERIFYING],
        TaskStatus.VERIFYING: [TaskStatus.CLOSED, TaskStatus.FIXING], # Allow reopen if verification fails
        TaskStatus.CLOSED: [TaskStatus.VERIFYING], # Allow reopen to verifying? Or Fixing?
    }
    # Note: Requirement says "New -> Confirmed -> Fixing -> Verifying -> Closed".
    # I will allow Verifying -> Fixing (rejection) and Closed -> Verifying (reopen) as practical defaults,
    # but strictly prioritization the linear flow. 
    # Actually, let's stick to the strict requirement first: "New -> Confirmed -> Fixing -> Verifying -> Closed".
    # And maybe allow Verifying -> Fixing because otherwise you can't fix a failed verification.
    
    STRICT_BUG_FLOW = {
        TaskStatus.NEW: [TaskStatus.CONFIRMED],
        TaskStatus.CONFIRMED: [TaskStatus.FIXING],
        TaskStatus.FIXING: [TaskStatus.VERIFYING],
        TaskStatus.VERIFYING: [TaskStatus.CLOSED, TaskStatus.FIXING], # Added loop back for failed verification
        TaskStatus.CLOSED: [TaskStatus.FIXING, TaskStatus.NEW], # Allow reopen
    }

    @classmethod
    def get_allowed_next_statuses(cls, category, current_status):
        """
        Get allowed next statuses for a given category and current status.
        """
        if category == TaskCategory.TASK:
            # Task allows transition to any Task-compatible status
            # Existing statuses: TODO, IN_PROGRESS, BLOCKED, IN_REVIEW, DONE, CLOSED
            # It should NOT allow Bug-specific statuses like NEW, CONFIRMED, FIXING, VERIFYING.
            return [
                TaskStatus.TODO,
                TaskStatus.IN_PROGRESS,
                TaskStatus.BLOCKED,
                TaskStatus.IN_REVIEW,
                TaskStatus.DONE,
                TaskStatus.CLOSED
            ]
        
        elif category == TaskCategory.BUG:
            # Bug allows specific flow
            # If current status is not in the flow (e.g. converted from Task), allow resetting to NEW?
            # Or assume valid start.
            
            allowed = cls.STRICT_BUG_FLOW.get(current_status, [])
            # Also always allow staying in same status
            if current_status not in allowed:
                # If we are in a weird state (e.g. TODO), allow jumping to NEW
                if current_status not in [TaskStatus.NEW, TaskStatus.CONFIRMED, TaskStatus.FIXING, TaskStatus.VERIFYING, TaskStatus.CLOSED]:
                    return [TaskStatus.NEW]
            return allowed

    @classmethod
    def validate_transition(cls, category, current_status, new_status):
        """
        Validate if a transition is allowed.
        """
        if current_status == new_status:
            return True
            
        allowed = cls.get_allowed_next_statuses(category, current_status)
        return new_status in allowed

    @classmethod
    def get_initial_status(cls, category):
        if category == TaskCategory.BUG:
            return TaskStatus.NEW
        return TaskStatus.TODO
