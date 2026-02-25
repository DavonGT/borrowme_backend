from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta

class Item(models.Model):
    STATUS_CHOICES = [
        ('AVAILABLE', 'Available'),
        ('BORROWED', 'Borrowed'),
        ('MAINTENANCE', 'Under Maintenance'),
    ]

    # This is the string your QR code will contain
    qr_code_id = models.CharField(max_length=100, unique=True, primary_key=True) 
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='AVAILABLE')
    is_bulk = models.BooleanField(default=False, help_text="Check if this is a group of identical items (like 5 brooms).")
    stock_quantity = models.IntegerField(default=1, help_text="Total number of items. Leave as 1 for unique items.")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.status})"

class Transaction(models.Model):
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('RETURNED', 'Returned'),
        ('OVERDUE', 'Overdue'), # Added a new status
    ]

    borrower = models.ForeignKey(User, on_delete=models.CASCADE, related_name='borrowed_items')
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='transactions')
    quantity = models.IntegerField(default=1, help_text="Number of items borrowed in this transaction")
    borrowed_at = models.DateTimeField(auto_now_add=True)
    due_date = models.DateTimeField() 
    returned_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')

    def save(self, *args, **kwargs):
        # Automatically set due date to 3 days from now if not provided
        if not self.due_date:
            self.due_date = timezone.now() + timedelta(days=3)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.item.name} borrowed by {self.borrower.username}"