"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-09-27 15:20:44

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('centres',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('city', sa.String(length=100), nullable=False),
    sa.Column('address', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name', 'city', name='uq_centre_name_city')
    )
    op.create_index(op.f('ix_centres_city'), 'centres', ['city'], unique=False)
    op.create_table('diagnostic_tests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('full_name', sa.String(length=120), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.Enum('USER', 'ADMIN', name='user_role'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    op.create_table('centre_tests',
    sa.Column('centre_id', sa.Integer(), nullable=False),
    sa.Column('test_id', sa.Integer(), nullable=False),
    sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.CheckConstraint('price > 0', name='ck_centre_test_price_positive'),
    sa.ForeignKeyConstraint(['centre_id'], ['centres.id'], ),
    sa.ForeignKeyConstraint(['test_id'], ['diagnostic_tests.id'], ),
    sa.PrimaryKeyConstraint('centre_id', 'test_id')
    )
    op.create_table('bookings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('centre_id', sa.Integer(), nullable=False),
    sa.Column('test_id', sa.Integer(), nullable=False),
    sa.Column('appointment_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('status', sa.Enum('PENDING', 'CONFIRMED', 'FAILED', 'CANCELLED', name='booking_status'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['centre_id', 'test_id'], ['centre_tests.centre_id', 'centre_tests.test_id'], name='fk_booking_centre_test'),
    sa.ForeignKeyConstraint(['centre_id'], ['centres.id'], ),
    sa.ForeignKeyConstraint(['test_id'], ['diagnostic_tests.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_bookings_status'), 'bookings', ['status'], unique=False)
    op.create_index(op.f('ix_bookings_user_id'), 'bookings', ['user_id'], unique=False)
    op.create_table('payments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('booking_id', sa.Integer(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('status', sa.Enum('SUCCESS', 'FAILED', name='payment_status'), nullable=False),
    sa.Column('source', sa.Enum('API', 'WEBHOOK', name='payment_source'), nullable=False),
    sa.Column('provider_ref', sa.String(length=64), nullable=False),
    sa.Column('idempotency_key', sa.String(length=100), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['booking_id'], ['bookings.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('idempotency_key'),
    sa.UniqueConstraint('provider_ref')
    )
    op.create_index(op.f('ix_payments_booking_id'), 'payments', ['booking_id'], unique=False)
    op.create_table('webhook_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('event_id', sa.String(length=100), nullable=False),
    sa.Column('booking_id', sa.Integer(), nullable=True),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('outcome', sa.String(length=50), nullable=True),
    sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['booking_id'], ['bookings.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('event_id')
    )


def downgrade() -> None:
    op.drop_table('webhook_events')
    op.drop_index(op.f('ix_payments_booking_id'), table_name='payments')
    op.drop_table('payments')
    op.drop_index(op.f('ix_bookings_user_id'), table_name='bookings')
    op.drop_index(op.f('ix_bookings_status'), table_name='bookings')
    op.drop_table('bookings')
    op.drop_table('centre_tests')
    op.drop_table('users')
    op.drop_table('diagnostic_tests')
    op.drop_index(op.f('ix_centres_city'), table_name='centres')
    op.drop_table('centres')

    # drop_table doesn't remove postgres enum types
    for enum_name in ("payment_source", "payment_status", "booking_status", "user_role"):
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
