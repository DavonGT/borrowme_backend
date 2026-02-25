from django.urls import path
from . import views

urlpatterns = [
    path('scan/<str:qr_code_id>/', views.scan_item, name='scan_item'),
    path('borrow/', views.borrow_item, name='borrow_item'),
    path('return/', views.return_item, name='return_item'),
]