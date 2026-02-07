# Database Migrations

This project uses [Alembic](https://alembic.sqlalchemy.org/) for database migrations.

## Overview

Migrations track changes to the database schema over time. When you modify models in `app/models/`, you need to create a migration to update the database schema.

## Running Migrations

### Initialize Database (First Time)

When setting up a fresh database, run:

```bash
python -m scripts.init_db
```

This will:
1. Create the database file if it doesn't exist
2. Run all pending migrations to create all tables

### Apply Migrations

To apply any pending migrations:

```bash
alembic upgrade head
```

### Check Migration Status

To see the current migration version:

```bash
alembic current
```

To see migration history:

```bash
alembic history
```

## Creating New Migrations

When you modify models (add/remove columns, tables, etc.):

1. **Auto-generate migration** (recommended):
   ```bash
   alembic revision --autogenerate -m "Description of changes"
   ```

2. **Review the generated migration** in `alembic/versions/`:
   - Check that it includes all expected changes
   - Verify it doesn't include unintended changes
   - Add any data migrations if needed

3. **Test the migration**:
   ```bash
   alembic upgrade head
   ```

4. **Commit the migration file** to version control

## Migration Workflow

1. Modify models in `app/models/`
2. Generate migration: `alembic revision --autogenerate -m "Add new field"`
3. Review the migration file
4. Apply migration: `alembic upgrade head`
5. Test your changes
6. Commit both model changes and migration file

## Rolling Back

To rollback the last migration:

```bash
alembic downgrade -1
```

To rollback to a specific revision:

```bash
alembic downgrade <revision_id>
```

## Important Notes

- **Always review auto-generated migrations** before applying them
- **Never edit existing migrations** that have been applied to production
- **Create new migrations** for schema changes instead of editing old ones
- **Test migrations** on a copy of production data before applying to production
- The `init_db.py` script automatically runs migrations, so you don't need to run them manually during initial setup

## Troubleshooting

### Migration conflicts
If you have conflicts between your database state and migrations:
1. Check current state: `alembic current`
2. Check what migrations are pending: `alembic heads`
3. If needed, stamp the database: `alembic stamp head` (use with caution)

### Database out of sync
If your database schema doesn't match your models:
1. Generate a new migration: `alembic revision --autogenerate -m "Sync schema"`
2. Review and apply it: `alembic upgrade head`
