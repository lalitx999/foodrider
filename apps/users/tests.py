from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from unittest.mock import patch
from apps.users.models import (
    ApplicationStatus, MerchantApplication, RiderApplication, RoleChangeRequest,
    RoleChangeStatus, User, UserRole,
)
from apps.users.services import approve_role_change_request, reject_role_change_request


class AuthenticationApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.line_verify_url = reverse('line-verify')
        self.google_verify_url = reverse('google-verify')
        self.profile_url = reverse('user-profile')
        self.set_role_url = reverse('set-role')

    def test_line_verify_missing_payload(self):
        """ทดสอบการส่ง payload ว่างเปล่า ต้องได้ 400 BAD REQUEST"""
        response = self.client.post(self.line_verify_url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error_code'], 'INVALID_PAYLOAD')

    def test_google_verify_missing_payload(self):
        """ทดสอบการส่ง payload ว่างเปล่าของ Google ต้องได้ 400 BAD REQUEST"""
        response = self.client.post(self.google_verify_url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error_code'], 'INVALID_PAYLOAD')

    @patch('apps.users.services.requests.post')
    def test_line_verify_success_creates_user(self, mock_post):
        """ทดสอบยิง LINE verify สำเร็จ ต้องสร้าง User ใหม่ role UNASSIGNED และออก JWT Token"""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            'sub': 'U1234567890abcdef',
            'name': 'Somchai LINE',
            'picture': 'https://example.com/profile.jpg'
        }

        response = self.client.post(self.line_verify_url, {'id_token': 'valid_line_token'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertIn('access', response.data['data'])
        self.assertIn('refresh', response.data['data'])

        # ตรวจสอบการสร้าง User ในฐานข้อมูล
        user = User.objects.get(line_user_id='U1234567890abcdef')
        self.assertEqual(user.display_name, 'Somchai LINE')
        self.assertEqual(user.role, UserRole.UNASSIGNED)

    def test_profile_requires_authentication(self):
        """ทดสอบเข้าถึง Profile โดยไม่ส่ง JWT Token ต้องได้ 401 UNAUTHORIZED"""
        response = self.client.get(self.profile_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_profile_with_valid_jwt(self):
        """ทดสอบเข้าถึง Profile พร้อม JWT Token ต้องได้ข้อมูล 200 OK"""
        user = User.objects.create(
            display_name='Test User',
            line_user_id='U99999999',
            role=UserRole.CUSTOMER
        )
        self.client.force_authenticate(user=user)
        response = self.client.get(self.profile_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertEqual(response.data['data']['display_name'], 'Test User')


class RoleChangeRequestServiceTests(TestCase):
    def setUp(self):
        self.reviewer = User.objects.create(display_name='Admin Reviewer', role=UserRole.ADMIN, is_staff=True)
        self.customer = User.objects.create(display_name='Customer User', role=UserRole.CUSTOMER)

    def test_approve_rider_request_creates_profile_and_switches_role(self):
        application = RiderApplication.objects.create(
            user=self.customer,
            full_name='Customer User',
            phone_number='0800000000',
            vehicle_plate='1กข-1234',
            driver_license_image='rider-applications/licenses/license.jpg',
            vehicle_image='rider-applications/vehicles/vehicle.jpg',
            status=ApplicationStatus.PENDING_REVIEW,
        )
        role_request = RoleChangeRequest.objects.create(
            user=self.customer,
            current_role=UserRole.CUSTOMER,
            requested_role=UserRole.RIDER,
            rider_application=application,
        )

        approve_role_change_request(role_request.id, self.reviewer, 'เอกสารครบถ้วน')

        self.customer.refresh_from_db()
        role_request.refresh_from_db()
        application.refresh_from_db()
        self.assertEqual(self.customer.role, UserRole.RIDER)
        self.assertTrue(hasattr(self.customer, 'rider_profile'))
        self.assertEqual(self.customer.rider_profile.vehicle_plate, '1กข-1234')
        self.assertEqual(application.status, ApplicationStatus.APPROVED)
        self.assertEqual(role_request.status, RoleChangeStatus.APPROVED)
        self.assertEqual(role_request.reviewed_by, self.reviewer)

    def test_reject_request_preserves_current_role(self):
        application = RiderApplication.objects.create(
            user=self.customer,
            full_name='Customer User',
            phone_number='0800000000',
            vehicle_plate='1กข-1234',
            driver_license_image='rider-applications/licenses/license.jpg',
            vehicle_image='rider-applications/vehicles/vehicle.jpg',
            status=ApplicationStatus.PENDING_REVIEW,
        )
        role_request = RoleChangeRequest.objects.create(
            user=self.customer,
            current_role=UserRole.CUSTOMER,
            requested_role=UserRole.RIDER,
            rider_application=application,
        )

        reject_role_change_request(role_request.id, self.reviewer, 'เอกสารไม่ครบ')

        self.customer.refresh_from_db()
        role_request.refresh_from_db()
        application.refresh_from_db()
        self.assertEqual(self.customer.role, UserRole.CUSTOMER)
        self.assertEqual(application.status, ApplicationStatus.REJECTED)
        self.assertEqual(role_request.status, RoleChangeStatus.REJECTED)
        self.assertEqual(role_request.admin_note, 'เอกสารไม่ครบ')
