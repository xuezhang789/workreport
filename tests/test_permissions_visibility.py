from django.test import TestCase, Client
from django.contrib.auth.models import User
from reports.models import Project, Task, DailyReport, Profile

class PermissionVisibilityTests(TestCase):
    def setUp(self):
        # Create users
        self.u_owner = User.objects.create_user('owner', 'owner@test.com', 'pass')
        self.u_member1 = User.objects.create_user('member1', 'm1@test.com', 'pass')
        self.u_member2 = User.objects.create_user('member2', 'm2@test.com', 'pass')
        self.u_outsider = User.objects.create_user('outsider', 'out@test.com', 'pass')
        
        # Create profiles
        Profile.objects.create(user=self.u_owner, position='mgr')
        Profile.objects.create(user=self.u_member1, position='dev')
        Profile.objects.create(user=self.u_member2, position='dev')
        Profile.objects.create(user=self.u_outsider, position='dev')

        # Create Projects
        self.p1 = Project.objects.create(name='Project 1', code='P1', owner=self.u_owner)
        self.p1.members.add(self.u_member1, self.u_member2)
        
        self.p2 = Project.objects.create(name='Project 2', code='P2', owner=self.u_owner)
        # Outsider is NOT in P1 or P2

        # Create Tasks
        self.t1 = Task.objects.create(title='T1', project=self.p1, user=self.u_member1)
        self.t2 = Task.objects.create(title='T2', project=self.p2, user=self.u_owner)
        
        # Create Reports
        self.r1 = DailyReport.objects.create(
            user=self.u_member1, date='2023-01-01', role='dev',
            today_work='Work on P1'
        )
        self.r1.projects.add(self.p1)
        
        self.r2 = DailyReport.objects.create(
            user=self.u_owner, date='2023-01-01', role='mgr',
            today_work='Work on P2'
        )
        self.r2.projects.add(self.p2)

        self.client = Client()

    def test_project_list_visibility(self):
        # Member 1 should see P1, not P2
        self.client.force_login(self.u_member1)
        resp = self.client.get('/reports/projects/')
        self.assertContains(resp, 'Project 1')
        self.assertNotContains(resp, 'Project 2')
        
        # Outsider see nothing
        self.client.force_login(self.u_outsider)
        resp = self.client.get('/reports/projects/')
        self.assertNotContains(resp, 'Project 1')
        self.assertNotContains(resp, 'Project 2')

    def test_task_list_visibility(self):
        # Member 1 should see T1 (in P1), not T2 (in P2)
        self.client.force_login(self.u_member1)
        resp = self.client.get('/reports/tasks/')
        self.assertContains(resp, 'T1')
        self.assertNotContains(resp, 'T2')

    def test_project_detail_permission(self):
        self.client.force_login(self.u_member1)
        # Can see P1
        resp = self.client.get(f'/reports/projects/{self.p1.id}/')
        self.assertEqual(resp.status_code, 200)
        
        # Cannot see P2
        resp = self.client.get(f'/reports/projects/{self.p2.id}/')
        self.assertEqual(resp.status_code, 403)

    def test_task_create_permission_validation(self):
        self.client.force_login(self.u_member1)
        # Try to create task in P2 (Forbidden)
        resp = self.client.post('/reports/tasks/admin/new/', {
            'title': 'Hack Task',
            'project': self.p2.id,
            'user': self.u_member1.id
        })
        # Should show error in form
        self.assertContains(resp, '没有权限')
        
        # Try to create task in P1 (Now Forbidden because member is not manager/owner)
        resp = self.client.post('/reports/tasks/admin/new/', {
            'title': 'Valid Task',
            'project': self.p1.id,
            'user': self.u_member1.id,
            'content': 'Some content'
        })
        self.assertContains(resp, '没有权限')

    def test_report_visibility(self):
        # Member 1 should see R1 (P1), not R2 (P2)
        # Assuming admin_reports is the view
        self.client.force_login(self.u_member1)
        resp = self.client.get('/reports/admin/reports/')
        self.assertContains(resp, 'Work on P1')
        self.assertNotContains(resp, 'Work on P2')

    def test_admin_task_list_visibility(self):
        # Member 1 should access admin_task_list (now unified) but only see P1 tasks
        self.client.force_login(self.u_member1)
        resp = self.client.get('/reports/tasks/admin/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'T1')
        self.assertNotContains(resp, 'T2')

    def test_user_search_api_visibility(self):
        # Member 1 should find Member 2 (same project) but not Outsider (if implemented strict)
        # Note: Outsider is not in any project, so strict logic might exclude him from results if he's not in accessible projects
        # Let's check: member 1 in P1. member 2 in P1. outsider in None.
        # Logic: users in accessible projects.
        # So Member 1 should see Member 2. Should NOT see Outsider.
        
        # Clear session throttle
        session = self.client.session
        session.clear()
        session.save()

        self.client.force_login(self.u_member1)
        resp = self.client.get('/reports/api/users/', {'q': 'member2'})
        if resp.status_code == 302:
             print("Redirected to:", resp.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'member2')
        
        # Reset session to clear throttle for next request
        # NOTE: clearing session logs out the user!
        # Re-login required
        
        # We don't need to clear session if we wait or just rely on different key?
        # The view uses _throttle with key 'user_search_api'
        # Just manually force login again
        
        self.client.force_login(self.u_member1)
        # We need to bypass throttle manually or wait? 
        # The test runs fast.
        # Hack: clear session but restore user id? No, force_login creates new session.
        
        # Let's just create a new client
        self.client = Client()
        self.client.force_login(self.u_member1)
        
        resp = self.client.get('/reports/api/users/', {'q': 'outsider'})
        # Should be 200 OK but empty result, NOT 302
        if resp.status_code == 302:
             print("Redirected to:", resp.url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'outsider')
        
        # Outsider (no projects) should get 403 on user search
        self.client.force_login(self.u_outsider)
        resp = self.client.get('/reports/api/users/')
        self.assertEqual(resp.status_code, 403)

    def test_super_admin_visibility(self):
        # Super admin should see everything
        admin = User.objects.create_superuser('admin', 'admin@test.com', 'pass')
        self.client.force_login(admin)
        
        # Projects
        resp = self.client.get('/reports/projects/')
        self.assertContains(resp, 'Project 1')
        self.assertContains(resp, 'Project 2')
        
        # Tasks
        resp = self.client.get('/reports/tasks/admin/')
        self.assertContains(resp, 'T1')
        self.assertContains(resp, 'T2')

    def test_manager_restricted_visibility(self):
        # Manager (u_owner) is owner of P1 and P2, so sees both.
        # Let's create a manager who is NOT owner/member of P2
        u_mgr2 = User.objects.create_user('mgr2', 'mgr2@test.com', 'pass')
        Profile.objects.create(user=u_mgr2, position='mgr') # Has manage permission
        
        # Add to P1 but not P2
        self.p1.managers.add(u_mgr2)
        
        self.client.force_login(u_mgr2)
        
        # Should see P1
        resp = self.client.get('/reports/projects/')
        self.assertContains(resp, 'Project 1')
        
        # Should NOT see P2 (even though is manager role, but not superuser and not in P2)
        self.assertNotContains(resp, 'Project 2')

    def test_project_edit_permission(self):
        # Member (u_member1) in P1. Should NOT be able to edit.
        self.client.force_login(self.u_member1)
        resp = self.client.get(f'/reports/projects/{self.p1.id}/edit/')
        self.assertEqual(resp.status_code, 403) # Forbidden
        
        # Owner (u_owner) should be able to edit
        self.client.force_login(self.u_owner)
        resp = self.client.get(f'/reports/projects/{self.p1.id}/edit/')
        self.assertEqual(resp.status_code, 200)

    def test_task_creation_by_member(self):
        # Member (u_member1) in P1. 
        # Requirement: "If not Owner/Manager ... forbid ... Publishing new tasks"
        # So member should be forbidden from creating task via admin interface?
        # Or at least via project detail link?
        
        self.client.force_login(self.u_member1)
        resp = self.client.post('/reports/tasks/admin/new/', {
            'title': 'Member Task',
            'project': self.p1.id,
            'user': self.u_member1.id,
            'content': 'Foo'
        })
        
        # Previously this was allowed (302). Now it should be forbidden (form error or 403).
        # We implemented form error.
        self.assertContains(resp, '没有权限')
        
        # Owner should be allowed
        self.client.force_login(self.u_owner)
        resp = self.client.post('/reports/tasks/admin/new/', {
            'title': 'Owner Task',
            'project': self.p1.id,
            'user': self.u_owner.id,
            'content': 'Bar'
        })
        self.assertEqual(resp.status_code, 302)

    def test_admin_task_edit_permission(self):
        # Member (u_member1) cannot edit task owned by Owner (t2 is in P2, t1 is in P1)
        # T1 is owned by Member1. Member1 CAN edit T1 (as task owner) even if not project manager.
        # But wait, requirement says "Ordinary user... only edit projects where they are Owner/Manager". 
        # But for tasks? "Details page... forbid publishing new tasks". 
        # Usually task owner can edit their own task.
        # Let's test T1 (owned by Member1)
        
        self.client.force_login(self.u_member1)
        # Correct URL is /reports/tasks/<pk>/edit/ based on urls.py
        resp = self.client.get(f'/reports/tasks/{self.t1.id}/edit/')
        self.assertEqual(resp.status_code, 200) # Task owner can edit
        
        # Member1 editing T2 (P2, Owner). Member1 has no access to P2.
        resp = self.client.get(f'/reports/tasks/{self.t2.id}/edit/')
        self.assertEqual(resp.status_code, 404) # Not found (because hidden)

        # What if Member1 tries to move T1 to P2? (He owns T1, but has no rights on P2)
        resp = self.client.post(f'/reports/tasks/{self.t1.id}/edit/', {
            'title': 'Moved Task',
            'project': self.p2.id, # Target P2
            'user': self.u_member1.id,
            'status': 'pending',
            'content': 'Moving'
        })
        self.assertContains(resp, '没有权限')
