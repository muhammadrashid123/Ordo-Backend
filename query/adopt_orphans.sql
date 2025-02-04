CREATE OR REPLACE FUNCTION  adopt_orphan(arg_product_id bigint) RETURNS VOID
LANGUAGE plpgsql
AS $$
    DECLARE
        last_id bigint;
    BEGIN
        INSERT INTO orders_product (
            name, description, category_id, updated_at, created_at, is_available_on_vendor, is_special_offer, vendors, child_count, is_manual
        )
        SELECT name, description, category_id, NOW(), NOW(), TRUE, FALSE, '{}', 0, FALSE
        FROM orders_product op2
        WHERE op2.id = arg_product_id
        RETURNING id INTO last_id;

        UPDATE orders_product opu
        SET parent_id = last_id
        WHERE opu.id = arg_product_id;
    END;
$$;

WITH parents as (
        SELECT DISTINCT parent_id FROM orders_product WHERE parent_id IS NOT NULL
    ),
    null_parents AS (
        SELECT * FROM orders_product WHERE parent_id IS NULL
    ),
    orphans AS (
        SELECT np.id FROM null_parents np
        LEFT JOIN parents p ON np.id = p.parent_id
        WHERE p.parent_id IS NULL
    )
-- The reason of select count(*) here is that tools like DataGrip return 500 rows by default
-- which results in incomplete query execution
SELECT COUNT(*) FROM (
    SELECT adopt_orphan(o.id)
    FROM orphans o
) adopted_orphans;

DROP FUNCTION IF EXISTS adopt_orphan(arg_product_id bigint);
