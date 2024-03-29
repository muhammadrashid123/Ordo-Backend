CREATE OR REPLACE FUNCTION fill_missing_office_products(office integer, vendor integer) RETURNS void AS $$
WITH office_products AS (SELECT *
                         FROM orders_officeproduct
                         WHERE office_id = office
                           and vendor_id = vendor),
     pop_records AS (SELECT op.id, op.vendor_id, oo.id as ofpid, op.category_id
                     FROM orders_product op
                              LEFT JOIN office_products oo on op.id = oo.product_id
                     WHERE op.vendor_id = vendor
                       and oo.id IS NULL),
     category_matching AS (SELECT pc.id as pcid, opc.id as opcid
                           FROM orders_productcategory pc
                                    JOIN orders_officeproductcategory opc on pc.slug = opc.slug
                           WHERE opc.office_id = office),
     to_be_inserted AS (SELECT CURRENT_TIMESTAMP                                              as "created_at",
                               CURRENT_TIMESTAMP                                              as "updated_at",
                               NULL::numeric                                                  as price,
                               FALSE                                                          as is_favorite,
                               FALSE                                                          as is_inventory,
                               office                                                         as office_id,
                               pr.category_id                                                 as office_category_id,
                               pr.id                                                          as product_id,
                               cm.opcid                                                       as office_product_category_id,
                               NULL::date                                                     as last_order_date,
                               CURRENT_TIMESTAMP - '15 days'::interval - (row_number() over ()) *
                                                                         '1 second'::interval as last_price_updated,
                               NULL                                                           as product_vendor_status,
                               NULL::numeric                                                  as last_order_price,
                               NULL                                                           as nickname,
                               CURRENT_TIMESTAMP - '1 day'::interval - (row_number() over ()) *
                                                                       '1 second'::interval   as price_expiration,
                               pr.vendor_id                                                   as vendor_id
                        FROM pop_records pr
                                 LEFT JOIN category_matching cm ON pr.category_id = cm.pcid)
INSERT
INTO orders_officeproduct
(created_at,
 updated_at,
 price,
 is_favorite,
 is_inventory,
 office_id,
 office_category_id,
 product_id,
 office_product_category_id,
 last_order_date,
 last_price_updated,
 product_vendor_status,
 last_order_price,
 nickname,
 price_expiration,
 vendor_id)
SELECT created_at,
       updated_at,
       price,
       is_favorite,
       is_inventory,
       office_id,
       office_category_id,
       product_id,
       office_product_category_id,
       last_order_date,
       last_price_updated,
       product_vendor_status,
       last_order_price,
       nickname,
       price_expiration,
       vendor_id
FROM to_be_inserted
ON CONFLICT DO NOTHING ;
$$ LANGUAGE SQL;


SELECT fill_missing_office_products(135, 2);
