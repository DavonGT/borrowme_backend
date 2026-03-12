from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_user, name='login_user'),
    path('admin/dashboard', views.admin_dashboard, name='admin_dashboard_no_slash'),
    path('admin/dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('scan/<str:qr_code_id>/', views.scan_item, name='scan_item'),
    path('borrow/', views.borrow_item, name='borrow_item'),
    path('return-auth/generate/', views.generate_return_token, name='generate_return_token'),
    path('return/', views.return_item, name='return_item'),
    path('my-borrows/', views.my_borrowed_items, name='my_borrows'),
    path('items/available/', views.available_items, name='available_items'),
]