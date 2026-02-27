from rest_framework import serializers
from .models import Item, Transaction
from django.contrib.auth.models import User
from django.db.models import Sum

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