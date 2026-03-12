# BorrowMe Backend API Contract

## Login Endpoint

This login endpoint returns the auth token plus role information so the Android app can route staff/admin users directly to the admin dashboard.

**URL**: `/api/login/`  
**Method**: `POST`

### Request Body

```json
{
  "username": "adminuser",
  "password": "admin-pass"
}
```

### Success Response

**HTTP 200 OK**

```json
{
  "token": "0a1b2c3d4e5f6g7h8i9j",
  "user_id": 5,
  "username": "adminuser",
  "is_staff": true,
  "is_superuser": false,
  "role": "admin",
  "start_destination": "admin_dashboard"
}
```

For normal borrower accounts:

```json
{
  "token": "0a1b2c3d4e5f6g7h8i9j",
  "user_id": 8,
  "username": "borrower1",
  "is_staff": false,
  "is_superuser": false,
  "role": "borrower",
  "start_destination": "borrow_home"
}
```

### Error Response

**HTTP 400 Bad Request**

```json
{
  "error": "Invalid username or password."
}
```

---

## Admin Dashboard Endpoint

This endpoint is for staff/admin users only and provides summary cards plus recent activity for the admin dashboard screen.

**URL**: `/api/admin/dashboard/`  
**Method**: `GET`  
**Auth**: Required (`Authorization: Token <token>`)  
**Access**: Staff/Admin only

### Success Response

**HTTP 200 OK**

```json
{
  "total_items": 25,
  "total_available_items": 18,
  "total_borrowed_items": 7,
  "active_transactions": 6,
  "overdue_transactions": 1,
  "total_users": 42,
  "overdue_borrowers": [
    {
      "transaction_id": 201,
      "borrower_id": 8,
      "borrower_name": "student1",
      "item": "QR-LAPTOP-001",
      "item_name": "Laptop",
      "quantity": 1,
      "due_date": "2026-03-09T09:10:00Z",
      "days_overdue": 3
    }
  ],
  "low_stock_items": [
    {
      "qr_code_id": "QR-CHAIR-001",
      "name": "Chair",
      "description": null,
      "status": "AVAILABLE",
      "is_bulk": true,
      "stock_quantity": 5,
      "available_quantity": 1
    }
  ],
  "active_borrowed_items": [
    {
      "id": 124,
      "item": "QR-SPEAKER-001",
      "item_name": "Speaker",
      "borrower": 9,
      "borrower_name": "student2",
      "quantity": 1,
      "borrowed_at": "2026-03-12T08:45:00Z",
      "due_date": "2026-03-15T08:45:00Z",
      "returned_at": null,
      "status": "ACTIVE"
    }
  ],
  "recent_returns": [
    {
      "id": 125,
      "item": "QR-MOUSE-001",
      "item_name": "Mouse",
      "borrower": 10,
      "borrower_name": "student3",
      "quantity": 1,
      "borrowed_at": "2026-03-10T10:00:00Z",
      "due_date": "2026-03-13T10:00:00Z",
      "returned_at": "2026-03-12T08:30:00Z",
      "status": "RETURNED"
    }
  ],
  "recent_transactions": [
    {
      "id": 123,
      "item": "QR-PROJECTOR-001",
      "item_name": "Projector",
      "borrower": 8,
      "borrower_name": "student1",
      "quantity": 1,
      "borrowed_at": "2026-03-12T09:10:00Z",
      "due_date": "2026-03-15T09:10:00Z",
      "returned_at": null,
      "status": "ACTIVE"
    }
  ]
}
```

### Error Responses

**HTTP 401 Unauthorized**

```json
{
  "detail": "Authentication credentials were not provided."
}
```

**HTTP 403 Forbidden**

```json
{
  "detail": "You do not have permission to perform this action."
}
```

---

## Staff Return Authorization Token Endpoint

This endpoint is used by the admin/staff app to generate a short-lived, one-time token.
The staff app should turn the returned `qr_payload` into a QR code and display it for the borrower to scan.
Generating a new token immediately invalidates any older unused return token.

**URL**: `/api/return-auth/generate/`  
**Method**: `POST`  
**Auth**: Required (`Authorization: Token <token>`)  
**Access**: Staff/Admin only

### Request Body

```json
{}
```

### Success Response

**HTTP 201 Created**

```json
{
  "return_token": "4fVh7v3l7f8lJ4c2bN7O0Yw1xR2sA3pQzK9mT6uV8wE",
  "qr_payload": "4fVh7v3l7f8lJ4c2bN7O0Yw1xR2sA3pQzK9mT6uV8wE",
  "expires_at": "2026-03-12T09:35:00Z",
  "valid_for_seconds": 300
}
```

### Error Responses

**HTTP 401 Unauthorized** (missing/invalid token)

```json
{
  "detail": "Authentication credentials were not provided."
}
```

**HTTP 403 Forbidden** (user is not staff/admin)

```json
{
  "detail": "You do not have permission to perform this action."
}
```

---

## Return Item Endpoint (Borrower + Staff QR Required)

The borrower must:
1. be logged in,
2. scan the staff-generated QR code,
3. submit the scanned token together with the `transaction_id`.

**URL**: `/api/return/`  
**Method**: `POST`  
**Auth**: Required (`Authorization: Token <token>`)

### Request Body

```json
{
  "transaction_id": 123,
  "return_token": "4fVh7v3l7f8lJ4c2bN7O0Yw1xR2sA3pQzK9mT6uV8wE"
}
```

### Success Response

**HTTP 200 OK**

```json
{
  "message": "Successfully returned 1 Projector(s)"
}
```

### Error Responses

**HTTP 400 Bad Request** (missing token field)

```json
{
  "return_token": [
    "This field is required."
  ]
}
```

**HTTP 400 Bad Request** (invalid or already used return token)

```json
{
  "error": "Invalid or already used return authorization token."
}
```

**HTTP 400 Bad Request** (expired return token)

```json
{
  "error": "Return authorization token has expired."
}
```

**HTTP 401 Unauthorized** (missing/invalid borrower token)

```json
{
  "detail": "Authentication credentials were not provided."
}
```

**HTTP 404 Not Found** (transaction does not belong to borrower, already returned, or invalid transaction id)

```json
{
  "error": "Transaction not found or already returned."
}
```

---

## Android Flow Notes

### Login Routing

- Call `/api/login/` instead of the default DRF token login.
- Check `start_destination` after login.
- If `start_destination` is `admin_dashboard`, open the admin dashboard screen immediately.
- If `start_destination` is `borrow_home`, open the normal borrower flow.

### Admin Dashboard Screen

- Load `/api/admin/dashboard/` right after admin/staff login.
- Use the summary numbers for dashboard cards.
- Use `overdue_borrowers` for overdue alerts.
- Use `low_stock_items` for low-stock warning cards.
- Use `active_borrowed_items` for currently borrowed item lists.
- Use `recent_returns` for the latest returned activity list.
- Use `recent_transactions` for a broader recent activity feed.

### Staff/Admin App

- Staff/admin users can manage return QR codes and dashboard data.
- Staff/admin users must not see borrower-only borrow actions.
- Call `/api/return-auth/generate/` when staff taps **Generate Return QR**.
- Convert `qr_payload` into a QR code locally in the Android app.
- Show the QR immediately and refresh it when expired.
- Treat each generated token as one-time use.
- Only one unused token can be active at a time; generating a new QR instantly invalidates the previous one.

### Borrower App

- Keep using the logged-in borrower token in the header.
- Borrow requests from staff/admin accounts will be rejected by the backend.
- On return flow, scan the staff QR first.
- Use the scanned QR content as `return_token`.
- Call `/api/return/` only after QR scan succeeds.
- Only show “Return successful” when status code is `200`.
- For `400/401/404`, show the backend error message and keep item in active-borrow list.
