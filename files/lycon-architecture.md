# LYCON Wallet — Architecture & Database Schema

**Status:** Development reference. No real customer funds should move until KYC/AML, security review, and a licensed Nigerian payment provider are in place.

## Environments
- **Development** — local, mock data
- **Sandbox** — mock payment provider, simulated transactions clearly labeled "not real money"
- **Production** — real licensed provider, real KYC, real funds. Kept fully separate from sandbox (separate credentials, database, and provider accounts).

## Services
| Service | Responsibility |
|---|---|
| Authentication | Registration, login, OTP, PIN, biometric session tokens, device/session management |
| KYC | Identity capture, BVN/NIN verification adapter, document/selfie upload, status workflow |
| Wallet | Balance reads, ledger entries, statements, receipts |
| Payment | Add-money flows via provider adapters (bank transfer, card, USSD) |
| Transfer | Send money (username/phone/account), bank transfer, beneficiary management |
| Bill Payment | Airtime, data, electricity, cable TV, education — via provider adapters |
| Notification | Push/SMS/email for transactions, security, KYC, promotions |
| Fraud/Security | Rate limiting, transaction limits, anomaly hooks, audit logging |
| Admin | Role-based back-office operations across all of the above |

All payment-touching services sit behind a **provider adapter interface** so a licensed provider can be swapped in without changing calling code. Never call a payment provider directly from a controller.

## Transaction engine rules
- Every transaction has a unique `transaction_reference` and an `idempotency_key` — duplicate requests with the same key return the original result, never a second transaction.
- Balance changes happen only inside a single atomic database transaction (row-level lock or equivalent), never as two separate read-then-write calls.
- The mobile/web client never writes a wallet balance directly — only a server-side service, after validating the transaction, may do so.
- Status lifecycle: `Pending → Successful | Failed | Reversed`. A reversal is its own ledger entry, never a silent edit of the original.

## Database schema (PostgreSQL / Supabase, UUID primary keys)

```
users
  id, phone, email, password_hash, pin_hash, status, created_at, updated_at

profiles
  id, user_id, full_name, date_of_birth, address, created_at, updated_at

kyc_records
  id, user_id, bvn_ref, nin_ref, id_document_url, selfie_url,
  status (pending|verified|rejected), reviewed_by, created_at, updated_at

wallets
  id, user_id, balance, currency, status, created_at, updated_at

wallet_transactions
  id, wallet_id, transaction_reference, idempotency_key, type, amount, fee,
  status, source, destination, description, created_at, completed_at

bank_accounts
  id, user_id, bank_name, account_number, account_name, is_verified, created_at

beneficiaries
  id, user_id, beneficiary_type, beneficiary_ref, label, created_at

transfers
  id, wallet_transaction_id, sender_wallet_id, receiver_wallet_id,
  bank_account_id, amount, status, created_at, completed_at

bill_payments
  id, wallet_transaction_id, category, provider, reference_id, amount, status, created_at

airtime_transactions
  id, wallet_transaction_id, network, phone_number, amount, status, created_at

data_transactions
  id, wallet_transaction_id, network, phone_number, plan, amount, status, created_at

merchants
  id, business_id, user_id, business_balance, status, created_at, updated_at

merchant_transactions
  id, merchant_id, wallet_transaction_id, amount, fee, status, created_at

businesses
  id, name, owner_user_id, status, created_at, updated_at

business_members
  id, business_id, user_id, role, permissions, created_at

notifications
  id, user_id, type, title, body, is_read, created_at

devices
  id, user_id, device_fingerprint, last_seen_at, is_trusted, created_at

security_events
  id, user_id, event_type, ip_address, device_id, risk_score, created_at

audit_logs
  id, admin_user_id, action, target_table, target_id, metadata, created_at

support_tickets
  id, user_id, subject, category, status, created_at, updated_at
```

All tables include `created_at`, `updated_at`, and `status` where applicable. Row Level Security should restrict every table to the owning `user_id`, with admin roles granted explicit, audited exceptions.

## Security baseline
- Password and PIN: hashed (never plain text), never logged
- Card details: tokenized via provider, CVV and full PAN never stored
- All traffic encrypted in transit; sensitive fields encrypted at rest
- OTP + PIN + optional biometric for transaction authorization
- Rate limiting and per-transaction/per-day limits enforced server-side
- Audit log entry for every admin action

## Admin roles
| Role | Scope |
|---|---|
| Super Admin | Full access, including system settings |
| Operations | Transactions, transfers, wallets, disputes |
| Compliance | KYC, fraud alerts, audit logs |
| Customer Support | Support tickets, read-only transaction lookup |
| Finance | Settlement, reports, reconciliation |

## Screens (reference list)
Splash, Onboarding, Register, Login, OTP, Create PIN, Home, Wallet, Send Money, Bank Transfer, Add Money, Withdraw, Airtime, Data, Bills, QR Scanner, QR Payment, Transaction Details, Receipt, Beneficiaries, Notifications, Profile, KYC, Security, Help Center, Support, Merchant Dashboard, Business Dashboard, Admin Dashboard.

## Before production
1. Register with a licensed Nigerian payment provider (e.g. an NDPR/CBN-compliant PSP) and complete their integration + compliance review.
2. Connect real BVN/NIN verification through an authorized provider.
3. Independent security audit and penetration test.
4. Legal review for CBN licensing/agent-banking requirements applicable to your operating model.
5. Replace the mock payment provider adapter with the production one — the calling code shouldn't need to change if the adapter interface was respected.
