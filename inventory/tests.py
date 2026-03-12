from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase
import hashlib
from datetime import timedelta

from .models import Item, Transaction, ReturnAuthorization


class ReturnItemAuthTests(APITestCase):
	def setUp(self):
		self.user = User.objects.create_user(username='alice', password='alice-pass-123')
		self.other_user = User.objects.create_user(username='bob', password='bob-pass-123')
		self.staff_user = User.objects.create_user(username='staff', password='staff-pass-123', is_staff=True)
		self.token = Token.objects.create(user=self.user)
		self.staff_token = Token.objects.create(user=self.staff_user)

		self.item = Item.objects.create(
			qr_code_id='QR-PROJECTOR-001',
			name='Projector',
			status='BORROWED',
			is_bulk=False,
			stock_quantity=1,
		)

		self.user_transaction = Transaction.objects.create(
			borrower=self.user,
			item=self.item,
			quantity=1,
			status='ACTIVE',
			due_date=timezone.now(),
		)

	def create_return_authorization(self, raw_token='staff-generated-token', expires_delta_minutes=5):
		return ReturnAuthorization.objects.create(
			token_hash=hashlib.sha256(raw_token.encode('utf-8')).hexdigest(),
			created_by=self.staff_user,
			expires_at=timezone.now() + timedelta(minutes=expires_delta_minutes),
		)

	def test_return_requires_token_authentication(self):
		response = self.client.post(
			'/api/return/',
			{
				'transaction_id': str(self.user_transaction.id),
				'return_token': 'staff-generated-token',
			},
			format='json',
		)

		self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

	def test_staff_can_generate_return_token(self):
		self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.staff_token.key}')

		response = self.client.post('/api/return-auth/generate/', {}, format='json')

		self.assertEqual(response.status_code, status.HTTP_201_CREATED)
		self.assertIn('return_token', response.data)
		self.assertIn('qr_payload', response.data)
		self.assertIn('expires_at', response.data)
		self.assertEqual(response.data['return_token'], response.data['qr_payload'])

	def test_non_staff_cannot_generate_return_token(self):
		self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')

		response = self.client.post('/api/return-auth/generate/', {}, format='json')

		self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

	def test_generating_new_return_token_invalidates_previous_active_token(self):
		self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.staff_token.key}')

		first_response = self.client.post('/api/return-auth/generate/', {}, format='json')
		second_response = self.client.post('/api/return-auth/generate/', {}, format='json')

		self.assertEqual(first_response.status_code, status.HTTP_201_CREATED)
		self.assertEqual(second_response.status_code, status.HTTP_201_CREATED)
		self.assertNotEqual(first_response.data['return_token'], second_response.data['return_token'])

		self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')

		first_return_attempt = self.client.post(
			'/api/return/',
			{
				'transaction_id': str(self.user_transaction.id),
				'return_token': first_response.data['return_token'],
			},
			format='json',
		)

		self.assertEqual(first_return_attempt.status_code, status.HTTP_400_BAD_REQUEST)
		self.assertEqual(first_return_attempt.data['error'], 'Return authorization token has expired.')

		second_return_attempt = self.client.post(
			'/api/return/',
			{
				'transaction_id': str(self.user_transaction.id),
				'return_token': second_response.data['return_token'],
			},
			format='json',
		)

		self.assertEqual(second_return_attempt.status_code, status.HTTP_200_OK)

	def test_return_rejects_missing_return_token(self):
		self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')

		response = self.client.post(
			'/api/return/',
			{'transaction_id': str(self.user_transaction.id)},
			format='json',
		)

		self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
		self.assertIn('return_token', response.data)

	def test_return_rejects_invalid_return_token(self):
		self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')

		response = self.client.post(
			'/api/return/',
			{
				'transaction_id': str(self.user_transaction.id),
				'return_token': 'wrong-token',
			},
			format='json',
		)

		self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
		self.assertEqual(response.data['error'], 'Invalid or already used return authorization token.')

	def test_return_rejects_expired_return_token(self):
		self.create_return_authorization(raw_token='expired-token', expires_delta_minutes=-1)
		self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')

		response = self.client.post(
			'/api/return/',
			{
				'transaction_id': str(self.user_transaction.id),
				'return_token': 'expired-token',
			},
			format='json',
		)

		self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
		self.assertEqual(response.data['error'], 'Return authorization token has expired.')

	def test_return_succeeds_with_valid_return_token(self):
		authorization = self.create_return_authorization(raw_token='valid-token')
		self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')

		response = self.client.post(
			'/api/return/',
			{
				'transaction_id': str(self.user_transaction.id),
				'return_token': 'valid-token',
			},
			format='json',
		)

		self.assertEqual(response.status_code, status.HTTP_200_OK)

		self.user_transaction.refresh_from_db()
		self.item.refresh_from_db()
		authorization.refresh_from_db()

		self.assertEqual(self.user_transaction.status, 'RETURNED')
		self.assertIsNotNone(self.user_transaction.returned_at)
		self.assertEqual(self.item.status, 'AVAILABLE')
		self.assertEqual(authorization.used_by, self.user)
		self.assertEqual(authorization.used_for_transaction, self.user_transaction)

	def test_return_token_cannot_be_reused(self):
		authorization = self.create_return_authorization(raw_token='one-time-token')
		second_item = Item.objects.create(
			qr_code_id='QR-MICROPHONE-001',
			name='Microphone',
			status='BORROWED',
			is_bulk=False,
			stock_quantity=1,
		)
		second_transaction = Transaction.objects.create(
			borrower=self.user,
			item=second_item,
			quantity=1,
			status='ACTIVE',
			due_date=timezone.now(),
		)

		self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
		first_response = self.client.post(
			'/api/return/',
			{
				'transaction_id': str(self.user_transaction.id),
				'return_token': 'one-time-token',
			},
			format='json',
		)
		second_response = self.client.post(
			'/api/return/',
			{
				'transaction_id': str(second_transaction.id),
				'return_token': 'one-time-token',
			},
			format='json',
		)

		authorization.refresh_from_db()

		self.assertEqual(first_response.status_code, status.HTTP_200_OK)
		self.assertEqual(second_response.status_code, status.HTTP_400_BAD_REQUEST)
		self.assertIsNotNone(authorization.used_at)

	def test_user_cannot_return_another_users_transaction(self):
		self.create_return_authorization(raw_token='valid-token')
		other_item = Item.objects.create(
			qr_code_id='QR-LAPTOP-001',
			name='Laptop',
			status='BORROWED',
			is_bulk=False,
			stock_quantity=1,
		)
		other_transaction = Transaction.objects.create(
			borrower=self.other_user,
			item=other_item,
			quantity=1,
			status='ACTIVE',
			due_date=timezone.now(),
		)

		self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
		response = self.client.post(
			'/api/return/',
			{
				'transaction_id': str(other_transaction.id),
				'return_token': 'valid-token',
			},
			format='json',
		)

		self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class AdminAccessTests(APITestCase):
	def setUp(self):
		self.borrower = User.objects.create_user(username='borrower', password='borrower-pass')
		self.second_borrower = User.objects.create_user(username='borrower2', password='borrower2-pass')
		self.staff_user = User.objects.create_user(username='adminuser', password='admin-pass', is_staff=True)
		self.borrower_token = Token.objects.create(user=self.borrower)
		self.staff_token = Token.objects.create(user=self.staff_user)

		self.item = Item.objects.create(
			qr_code_id='QR-SPEAKER-001',
			name='Speaker',
			status='AVAILABLE',
			is_bulk=False,
			stock_quantity=1,
		)
		self.transaction = Transaction.objects.create(
			borrower=self.borrower,
			item=self.item,
			quantity=1,
			status='ACTIVE',
			due_date=timezone.now(),
		)
		self.bulk_item = Item.objects.create(
			qr_code_id='QR-CHAIR-001',
			name='Chair',
			status='AVAILABLE',
			is_bulk=True,
			stock_quantity=5,
		)
		self.low_stock_transaction = Transaction.objects.create(
			borrower=self.borrower,
			item=self.bulk_item,
			quantity=4,
			status='ACTIVE',
			due_date=timezone.now(),
		)
		self.overdue_item = Item.objects.create(
			qr_code_id='QR-LAPTOP-OVERDUE',
			name='Laptop',
			status='BORROWED',
			is_bulk=False,
			stock_quantity=1,
		)
		self.overdue_transaction = Transaction.objects.create(
			borrower=self.second_borrower,
			item=self.overdue_item,
			quantity=1,
			status='OVERDUE',
			due_date=timezone.now() - timedelta(days=3),
		)
		self.returned_item = Item.objects.create(
			qr_code_id='QR-MOUSE-RETURNED',
			name='Mouse',
			status='AVAILABLE',
			is_bulk=False,
			stock_quantity=1,
		)
		self.returned_transaction = Transaction.objects.create(
			borrower=self.borrower,
			item=self.returned_item,
			quantity=1,
			status='RETURNED',
			due_date=timezone.now() - timedelta(days=2),
			returned_at=timezone.now() - timedelta(hours=1),
		)

	def test_login_returns_admin_start_destination_for_staff(self):
		response = self.client.post(
			'/api/login/',
			{'username': 'adminuser', 'password': 'admin-pass'},
			format='json',
		)

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertEqual(response.data['role'], 'admin')
		self.assertEqual(response.data['start_destination'], 'admin_dashboard')
		self.assertTrue(response.data['is_staff'])

	def test_login_returns_borrower_start_destination_for_regular_user(self):
		response = self.client.post(
			'/api/login/',
			{'username': 'borrower', 'password': 'borrower-pass'},
			format='json',
		)

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertEqual(response.data['role'], 'borrower')
		self.assertEqual(response.data['start_destination'], 'borrow_home')
		self.assertFalse(response.data['is_staff'])

	def test_admin_dashboard_is_accessible_to_staff(self):
		self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.staff_token.key}')

		response = self.client.get('/api/admin/dashboard/')

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertIn('total_items', response.data)
		self.assertIn('recent_transactions', response.data)
		self.assertIn('overdue_borrowers', response.data)
		self.assertIn('low_stock_items', response.data)
		self.assertIn('active_borrowed_items', response.data)
		self.assertIn('recent_returns', response.data)
		self.assertTrue(any(item['name'] == 'Chair' for item in response.data['low_stock_items']))
		self.assertTrue(any(entry['borrower_name'] == 'borrower2' for entry in response.data['overdue_borrowers']))
		self.assertTrue(any(entry['item_name'] == 'Mouse' for entry in response.data['recent_returns']))

	def test_admin_dashboard_blocks_non_staff(self):
		self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.borrower_token.key}')

		response = self.client.get('/api/admin/dashboard/')

		self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

	def test_staff_account_cannot_borrow_items(self):
		self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.staff_token.key}')

		response = self.client.post(
			'/api/borrow/',
			{'qr_code_id': self.item.qr_code_id, 'quantity': 1},
			format='json',
		)

		self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
		self.assertEqual(response.data['error'], 'Admin/staff accounts are not allowed to borrow items.')
