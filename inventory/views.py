import hashlib
import secrets
from datetime import timedelta

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.utils import timezone
from .models import Item, Transaction, ReturnAuthorization
from .serializers import (
    AdminDashboardSerializer,
    ItemSerializer,
    LoginSerializer,
    TransactionSerializer,
    ReturnItemSerializer,
    ReturnAuthorizationResponseSerializer,
)
from django.db import transaction
from rest_framework.decorators import permission_classes, authentication_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.authentication import TokenAuthentication
from django.db.models import Sum
from django.db.models import Q


RETURN_AUTH_TOKEN_TTL_MINUTES = 5


def _hash_return_token(raw_token):
    return hashlib.sha256(raw_token.encode('utf-8')).hexdigest()


@api_view(['POST'])
def login_user(request):
    serializer = LoginSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    username = serializer.validated_data['username']
    password = serializer.validated_data['password']
    user = authenticate(username=username, password=password)

    if not user:
        return Response({'error': 'Invalid username or password.'}, status=status.HTTP_400_BAD_REQUEST)

    token, _ = Token.objects.get_or_create(user=user)

    return Response(
        {
            'token': token.key,
            'user_id': user.id,
            'username': user.username,
            'is_staff': user.is_staff,
            'is_superuser': user.is_superuser,
            'role': 'admin' if user.is_staff else 'borrower',
            'start_destination': 'admin_dashboard' if user.is_staff else 'borrow_home',
        },
        status=status.HTTP_200_OK,
    )


@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAdminUser])
def admin_dashboard(request):
    recent_transactions = Transaction.objects.select_related('item', 'borrower').order_by('-borrowed_at')[:10]
    overdue_borrowers = Transaction.objects.select_related('item', 'borrower').filter(
        status='OVERDUE'
    ).order_by('due_date')[:10]
    low_stock_items = Item.objects.filter(is_bulk=True).order_by('name')
    low_stock_items = [item for item in low_stock_items if ItemSerializer(item).data['available_quantity'] <= 2][:10]
    active_borrowed_items = Transaction.objects.select_related('item', 'borrower').filter(
        status='ACTIVE'
    ).order_by('-borrowed_at')[:10]
    recent_returns = Transaction.objects.select_related('item', 'borrower').filter(
        status='RETURNED',
        returned_at__isnull=False,
    ).order_by('-returned_at')[:10]

    dashboard_data = {
        'total_items': Item.objects.count(),
        'total_available_items': Item.objects.filter(Q(is_bulk=True) | Q(status='AVAILABLE')).count(),
        'total_borrowed_items': Transaction.objects.filter(status='ACTIVE').aggregate(total=Sum('quantity'))['total'] or 0,
        'active_transactions': Transaction.objects.filter(status='ACTIVE').count(),
        'overdue_transactions': Transaction.objects.filter(status='OVERDUE').count(),
        'total_users': User.objects.filter(is_staff=False).count(),
        'recent_transactions': recent_transactions,
        'overdue_borrowers': overdue_borrowers,
        'low_stock_items': low_stock_items,
        'active_borrowed_items': active_borrowed_items,
        'recent_returns': recent_returns,
    }
    serializer = AdminDashboardSerializer(dashboard_data)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAdminUser])
def generate_return_token(request):
    with transaction.atomic():
        now = timezone.now()
        ReturnAuthorization.objects.filter(
            used_at__isnull=True,
            expires_at__gt=now,
        ).update(expires_at=now)

        raw_token = secrets.token_urlsafe(32)
        expires_at = now + timedelta(minutes=RETURN_AUTH_TOKEN_TTL_MINUTES)

        ReturnAuthorization.objects.create(
            token_hash=_hash_return_token(raw_token),
            created_by=request.user,
            expires_at=expires_at,
        )

    response_serializer = ReturnAuthorizationResponseSerializer(
        {
            'return_token': raw_token,
            'qr_payload': raw_token,
            'expires_at': expires_at,
            'valid_for_seconds': RETURN_AUTH_TOKEN_TTL_MINUTES * 60,
        }
    )
    return Response(response_serializer.data, status=status.HTTP_201_CREATED)

@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def scan_item(request, qr_code_id):
    """Fetches item details when the Android app scans a QR code."""
    try:
        item = Item.objects.get(qr_code_id=qr_code_id)
        serializer = ItemSerializer(item)
        return Response(serializer.data)
    except Item.DoesNotExist:
        return Response({'error': 'Item not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def borrow_item(request):
    qr_code_id = request.data.get('qr_code_id')
    # The Android app will now send how many items the user wants
    requested_quantity = int(request.data.get('quantity', 1)) 
    user = request.user 

    if user.is_staff:
        return Response(
            {'error': 'Admin/staff accounts are not allowed to borrow items.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        with transaction.atomic():
            item = Item.objects.select_for_update().get(qr_code_id=qr_code_id)

            if item.is_bulk:
                # Add up the 'quantity' of all active transactions for this item
                active_borrows_data = Transaction.objects.filter(item=item, status='ACTIVE').aggregate(Sum('quantity'))
                current_active_borrows = active_borrows_data['quantity__sum'] or 0
                
                # Check if there are enough chairs left in stock
                if current_active_borrows + requested_quantity > item.stock_quantity:
                    available_left = item.stock_quantity - current_active_borrows
                    return Response({
                        'error': f'Not enough in stock. Only {available_left} {item.name}s available.'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            else:
                # If it's a unique item (like a projector), force quantity to 1
                requested_quantity = 1
                if item.status != 'AVAILABLE':
                    return Response({'error': f'Item is currently {item.status.lower()}'}, status=status.HTTP_400_BAD_REQUEST)
                
                item.status = 'BORROWED'
                item.save()

            # Create the transaction with the requested quantity
            new_transaction = Transaction.objects.create(
                borrower=user, 
                item=item, 
                quantity=requested_quantity
            )

        return Response({
            'message': f'Successfully borrowed {requested_quantity} {item.name}(s)',
            'due_date': new_transaction.due_date
        }, status=status.HTTP_200_OK)

    except Item.DoesNotExist:
        return Response({'error': 'Item not found'}, status=status.HTTP_404_NOT_FOUND)
        
@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def return_item(request):
    """Marks a SPECIFIC active transaction as returned."""
    serializer = ReturnItemSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    transaction_id = serializer.validated_data['transaction_id']
    return_token = serializer.validated_data['return_token']
    user = request.user 
    
    try:
        with transaction.atomic():
            authorization = ReturnAuthorization.objects.select_for_update().get(
                token_hash=_hash_return_token(return_token),
                used_at__isnull=True,
            )

            if authorization.is_expired():
                return Response(
                    {'error': 'Return authorization token has expired.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Find the EXACT transaction the user clicked on
            transaction_record = Transaction.objects.select_for_update().get(
                id=transaction_id,
                borrower=user,
                status='ACTIVE'
            )

            item = transaction_record.item

            # Close the specific transaction
            returned_at = timezone.now()
            transaction_record.status = 'RETURNED'
            transaction_record.returned_at = returned_at
            transaction_record.save()

            # Only change the physical item's status back to AVAILABLE if it's a unique item
            if not item.is_bulk:
                item.status = 'AVAILABLE'
                item.save()

            authorization.used_at = returned_at
            authorization.used_by = user
            authorization.used_for_transaction = transaction_record
            authorization.save()

        return Response({
            'message': f'Successfully returned {transaction_record.quantity} {item.name}(s)'
        }, status=status.HTTP_200_OK)

    except ReturnAuthorization.DoesNotExist:
        return Response(
            {'error': 'Invalid or already used return authorization token.'},
            status=status.HTTP_400_BAD_REQUEST
        )
    except Transaction.DoesNotExist:
        return Response(
            {'error': "Transaction not found or already returned."}, 
            status=status.HTTP_404_NOT_FOUND
        )
    

@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def my_borrowed_items(request):
    """Returns a list of ACTIVE transactions for the logged-in user."""
    transactions = Transaction.objects.filter(borrower=request.user, status='ACTIVE').order_by('-borrowed_at')
    serializer = TransactionSerializer(transactions, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def available_items(request):
    """Returns a list of items that can be borrowed."""
    # This fetches items that are either bulk (chairs/brooms) OR unique items that are strictly 'AVAILABLE'
    items = Item.objects.filter(Q(is_bulk=True) | Q(status='AVAILABLE')).order_by('name')
    
    serializer = ItemSerializer(items, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)