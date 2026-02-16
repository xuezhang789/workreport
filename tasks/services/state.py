from core.constants import TaskStatus, TaskCategory

class TaskStateService:
    """
    任务状态机服务 (State Machine Service)。
    
    负责定义和验证不同类型任务（普通任务、Bug）的状态流转规则。
    - 普通任务 (TASK): 允许在任意有效状态间自由流转。
    - 缺陷 (BUG): 必须遵循严格的线性工作流 (New -> Confirmed -> Fixing -> Verifying -> Closed)。
    """
    
    # Bug 的严格流转规则定义
    # Key: 当前状态
    # Value: 允许流转到的下一个状态列表
    STRICT_BUG_FLOW = {
        TaskStatus.NEW: [TaskStatus.CONFIRMED], # 新建 -> 确认
        TaskStatus.CONFIRMED: [TaskStatus.FIXING], # 确认 -> 修复中
        TaskStatus.FIXING: [TaskStatus.VERIFYING], # 修复中 -> 验证中
        TaskStatus.VERIFYING: [TaskStatus.CLOSED, TaskStatus.FIXING], # 验证中 -> 关闭(通过) 或 修复中(不通过)
        TaskStatus.CLOSED: [TaskStatus.NEW, TaskStatus.FIXING], # 关闭 -> 新建(重开) 或 修复中
    }

    @classmethod
    def get_allowed_next_statuses(cls, category, current_status):
        """
        根据任务分类和当前状态，获取所有允许跳转的目标状态列表。
        
        Args:
            category (str): 任务分类 (TASK/BUG)
            current_status (str): 当前状态代码
            
        Returns:
            list: 允许的下一个状态代码列表
        """
        if category == TaskCategory.TASK:
            # 普通任务没有严格流程限制，允许流转到任何属于 "任务" 范畴的状态
            # 注意：不应包含 BUG 专有的状态 (如 NEW, VERIFYING 等，如果它们是互斥的话)
            # 但目前系统中状态定义可能混合使用。
            # 这里返回所有非 Bug 专用状态。
            return [
                TaskStatus.TODO,
                TaskStatus.IN_PROGRESS,
                TaskStatus.BLOCKED,
                TaskStatus.IN_REVIEW,
                TaskStatus.DONE,
                TaskStatus.CLOSED
            ]
        
        elif category == TaskCategory.BUG:
            # Bug 遵循严格流程
            
            # 1. 如果当前状态是 Bug 流程中的有效状态，返回配置的下一跳
            if current_status in cls.STRICT_BUG_FLOW:
                return cls.STRICT_BUG_FLOW[current_status]
            
            # 2. 异常处理：如果当前状态不是 Bug 的有效状态（例如从普通任务转换而来，处于 TODO 状态）
            # 则允许重置为 Bug 的初始状态 (NEW)
            return [TaskStatus.NEW]
            
        return []

    @classmethod
    def validate_transition(cls, category, current_status, new_status):
        """
        验证状态流转是否合法。
        
        Args:
            category (str): 任务分类
            current_status (str): 当前状态
            new_status (str): 目标状态
            
        Returns:
            bool: 如果流转合法返回 True，否则 False
        """
        # 允许原地更新（不改变状态）
        if current_status == new_status:
            return True
            
        allowed = cls.get_allowed_next_statuses(category, current_status)
        return new_status in allowed

    @classmethod
    def get_initial_status(cls, category):
        """
        获取指定分类的默认初始状态。
        """
        if category == TaskCategory.BUG:
            return TaskStatus.NEW
        return TaskStatus.TODO
