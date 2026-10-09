ALTER TABLE live_rooms
    ADD COLUMN active_product_id text REFERENCES products(id);
