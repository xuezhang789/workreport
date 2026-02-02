from core.constants import TaskStatus, TaskCategory

class TaskStateService:
    """
    处理任务状态流转和验证的服务。
    """
    
    BUG_FLOW = {
        TaskStatus.NEW: [TaskStatus.CONFIRMED],
        TaskStatus.CONFIRMED: [TaskStatus.FIXING],
        TaskStatus.FIXING: [TaskStatus.VERIFYING],
        TaskStatus.VERIFYING: [TaskStatus.CLOSED, TaskStatus.FIXING], # 允许如果验证失败重新打开
        TaskStatus.CLOSED: [TaskStatus.VERIFYING], # 允许重新打开到验证? 或者修复?
    }
    # 注意: 需求说是 "New -> Confirmed -> Fixing -> Verifying -> Closed".
    # 我将允许 Verifying -> Fixing (拒绝) 和 Closed -> Verifying (重新打开) 作为实际默认值，
    # 但严格优先考虑线性流程。
    # 实际上，让我们先坚持严格的需求: "New -> Confirmed -> Fixing -> Verifying -> Closed".
    # 并允许 Verifying -> Fixing 因为否则你无法修复失败的验证。
    
    STRICT_BUG_FLOW = {
        TaskStatus.NEW: [TaskStatus.CONFIRMED],
        TaskStatus.CONFIRMED: [TaskStatus.FIXING],
        TaskStatus.FIXING: [TaskStatus.VERIFYING],
        TaskStatus.VERIFYING: [TaskStatus.CLOSED, TaskStatus.FIXING], # 添加回环用于失败的验证
        TaskStatus.CLOSED: [TaskStatus.FIXING, TaskStatus.NEW], # 允许重新打开
    }

    @classmethod
    def get_allowed_next_statuses(cls, category, current_status):
        """
        获取给定分类和当前状态的允许的下一个状态。
        """
        if category == TaskCategory.TASK:
            # 任务允许流转到任何与任务兼容的状态
            # 现有状态: TODO, IN_PROGRESS, BLOCKED, IN_REVIEW, DONE, CLOSED
            # 它不应该允许 Bug 特定的状态，如 NEW, CONFIRMED, FIXING, VERIFYING。
            return [
                TaskStatus.TODO,
                TaskStatus.IN_PROGRESS,
                TaskStatus.BLOCKED,
                TaskStatus.IN_REVIEW,
                TaskStatus.DONE,
                TaskStatus.CLOSED
            ]
        
        elif category == TaskCategory.BUG:
            # Bug 允许特定流程
            # 如果当前状态不在流程中（例如从任务转换而来），允许重置为 NEW？
            # 或者假设有效的开始。
            
            allowed = cls.STRICT_BUG_FLOW.get(current_status, [])
            # 总是允许保持在同一状态
            if current_status not in allowed:
                # 如果我们处于奇怪的状态（例如 TODO），允许跳转到 NEW
                if current_status not in [TaskStatus.NEW, TaskStatus.CONFIRMED, TaskStatus.FIXING, TaskStatus.VERIFYING, TaskStatus.CLOSED]:
                    return [TaskStatus.NEW]
            return allowed

    @classmethod
    def validate_transition(cls, category, current_status, new_status):
        """
        验证流转是否允许。
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
