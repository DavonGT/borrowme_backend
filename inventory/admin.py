from django.contrib import admin
from .models import Item, Transaction

@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    # Columns to display in the list view
    list_display = ('name', 'qr_code_id', 'status', 'created_at')
    # Adds a search bar to search by name or QR code
    search_fields = ('name', 'qr_code_id')
    # Adds a filter sidebar to easily find 'AVAILABLE' vs 'BORROWED' items
    list_filter = ('status',)

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('item', 'borrower', 'status', 'borrowed_at', 'returned_at')
    list_filter = ('status', 'borrowed_at')
    # Allows searching by the related item's name or the borrower's username
    search_fields = ('item__name', 'borrower__username')