
import os
import django

# Set required environment variables before setup
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
os.environ.setdefault("DJANGO_SECRET_KEY", "test-key-for-diagnosis")
os.environ.setdefault("DJANGO_DEBUG", "True")

django.setup()

import json
from django.db.models import Q
from django.test import RequestFactory
from django.contrib.auth import get_user_model
from projects.models import Project
from reports.utils import get_accessible_projects

def diagnose():
    print("--- 诊断开始 ---")
    User = get_user_model()
    
    # 1. 检查是否有任何活跃项目
    total_projects = Project.objects.filter(is_active=True).count()
    print(f"活跃项目总数: {total_projects}")
    if total_projects == 0:
        print("警告: 数据库中没有活跃项目！")
        return

    # 2. 检查是否有用户负责或参与项目
    users_with_projects = set()
    for p in Project.objects.filter(is_active=True):
        if p.owner:
            users_with_projects.add(p.owner)
        for m in p.members.all():
            users_with_projects.add(m)
        for m in p.managers.all():
            users_with_projects.add(m)
            
    print(f"关联了项目的用户总数: {len(users_with_projects)}")
    
    # 3. 模拟 API 逻辑 (针对前 5 个关联项目的用户)
    test_users = list(users_with_projects)[:5]
    if not test_users:
        # 如果没有关联用户，尝试找一个普通用户
        test_users = list(User.objects.filter(is_superuser=False)[:1])
        print("警告: 没有用户直接关联项目，尝试使用任意普通用户进行测试")

    for user in test_users:
        print(f"\n--- 测试用户: {user.username} (ID: {user.id}) ---")
        
        # A. 检查 get_accessible_projects
        accessible_qs = get_accessible_projects(user)
        accessible_count = accessible_qs.count()
        print(f"get_accessible_projects 返回数量: {accessible_count}")
        
        # B. 检查 API 中的直接查询逻辑 (Lite Mode)
        direct_filter = Q(owner=user) | Q(managers=user) | Q(members=user)
        cached_ids = list(accessible_qs.values_list('id', flat=True))
        
        base_qs = Project.objects.filter(is_active=True)
        api_qs = base_qs.filter(Q(id__in=cached_ids) | direct_filter).distinct()
        api_count = api_qs.count()
        print(f"API Lite 逻辑返回数量: {api_count}")
        
        if api_count > 0:
            print(f"可访问项目示例: {[p.code for p in api_qs[:3]]}")
        else:
            print("该用户没有任何可访问的项目！")
            # 进一步诊断为何没有
            is_owner = Project.objects.filter(owner=user, is_active=True).exists()
            is_member = Project.objects.filter(members=user, is_active=True).exists()
            is_manager = Project.objects.filter(managers=user, is_active=True).exists()
            print(f"直接检查: Is Owner? {is_owner}, Is Member? {is_member}, Is Manager? {is_manager}")

if __name__ == "__main__":
    diagnose()
