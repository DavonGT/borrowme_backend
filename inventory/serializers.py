from rest_framework import serializers
from .models import Item, Transaction
from django.db.models import Sum
from django.utils import timezone


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(required=True)
    password = serializers.CharField(required=True, trim_whitespace=False, write_only=True)

class ItemSerializer(serializers.ModelSerializer):
    # Create a custom field that calculates the available stock on the fly
    available_quantity = serializers.SerializerMethodField()

    class Meta:
        model = Item
        fields = [
            'qr_code_id', 'name', 
            'description', 'status', 'is_bulk', 'stock_quantity', 'available_quantity'
        ]

    def get_available_quantity(self, obj):
        if obj.is_bulk:
            # Sum up all active transactions for this specific item
            active_borrows = Transaction.objects.filter(
                item=obj, 
                status='ACTIVE'
            ).aggregate(Sum('quantity'))['quantity__sum'] or 0
            
            # Subtract active borrows from the total stock
            return obj.stock_quantity - active_borrows
        else:
            # If it's a unique item (like a projector), it's either 1 or 0
            return 1 if obj.status == 'AVAILABLE' else 0

class TransactionSerializer(serializers.ModelSerializer):
    item_name = serializers.ReadOnlyField(source='item.name')
    borrower_name = serializers.ReadOnlyField(source='borrower.username')

    class Meta:
        model = Transaction
        fields = ['id', 'item', 'item_name', 'borrower', 'borrower_name','quantity', 'borrowed_at', 'due_date', 'returned_at', 'status']


class ReturnItemSerializer(serializers.Serializer):
    transaction_id = serializers.IntegerField(required=True)
    return_token = serializers.CharField(required=True, trim_whitespace=True, write_only=True)


class ReturnAuthorizationResponseSerializer(serializers.Serializer):
    return_token = serializers.CharField(read_only=True)
    qr_payload = serializers.CharField(read_only=True)
    expires_at = serializers.DateTimeField(read_only=True)
    valid_for_seconds = serializers.IntegerField(read_only=True)


class AdminDashboardSerializer(serializers.Serializer):
    total_items = serializers.IntegerField(read_only=True)
    total_available_items = serializers.IntegerField(read_only=True)
    total_borrowed_items = serializers.IntegerField(read_only=True)
    active_transactions = serializers.IntegerField(read_only=True)
    overdue_transactions = serializers.IntegerField(read_only=True)
    total_users = serializers.IntegerField(read_only=True)
    recent_transactions = TransactionSerializer(many=True, read_only=True)
    overdue_borrowers = serializers.SerializerMethodField()
    low_stock_items = ItemSerializer(many=True, read_only=True)
    active_borrowed_items = TransactionSerializer(many=True, read_only=True)
    recent_returns = TransactionSerializer(many=True, read_only=True)

    def get_overdue_borrowers(self, obj):
        overdue_transactions = obj.get('overdue_borrowers', [])
        now = timezone.now()

        return [
            {
                'transaction_id': transaction.id,
                'borrower_id': transaction.borrower_id,
                'borrower_name': transaction.borrower.username,
                'item': transaction.item_id,
                'item_name': transaction.item.name,
                'quantity': transaction.quantity,
                'due_date': transaction.due_date,
                'days_overdue': max((now - transaction.due_date).days, 0),
            }
            for transaction in overdue_transactions
        ]