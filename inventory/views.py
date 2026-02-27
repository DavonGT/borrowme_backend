from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.utils import timezone
from .models import Item, Transaction
from .serializers import ItemSerializer, TransactionSerializer
from django.contrib.auth.models import User
from django.db import transaction
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication
from django.db.models import Sum

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
    """Marks an active transaction as returned and frees up the item."""
    qr_code_id = request.data.get('qr_code_id')
    user = request.user
    
    try:
        item = Item.objects.get(qr_code_id=qr_code_id)
        transaction_record = Transaction.objects.filter(
            item=item, 
            borrower=user, 
            status='ACTIVE'
        ).order_by('borrowed_at').first()

        if not transaction_record:
            return Response(
                {'error': "You don't have any active borrows for this item."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        # Close the user's specific transaction
        transaction_record.status = 'RETURNED'
        transaction_record.returned_at = timezone.now()
        transaction_record.save()

        # Only change the physical item's status back to AVAILABLE if it's a unique item (like a projector)
        if not item.is_bulk:
            item.status = 'AVAILABLE'
            item.save()

        return Response({
            'message': f'Successfully returned {transaction_record.quantity} {item.name}(s)'
        }, status=status.HTTP_200_OK)

    except Item.DoesNotExist:
        return Response({'error': 'Item not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
         return Response({'error': 'An error occurred processing your request.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    

@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def my_borrowed_items(request):
    """Returns a list of ACTIVE transactions for the logged-in user."""
    transactions = Transaction.objects.filter(borrower=request.user, status='ACTIVE').order_by('-borrowed_at')
    serializer = TransactionSerializer(transactions, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)