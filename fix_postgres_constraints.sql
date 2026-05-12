-- =============================================================================
-- Патч схемы PostgreSQL: composite UNIQUE на posts и comments
-- =============================================================================
-- Применять единым блоком (BEGIN/COMMIT) на пустой/боевой БД.
-- Если на каком-то шаге упадёт — транзакция откатится, БД останется в исходном
-- состоянии.
--
-- ПЕРЕД ЗАПУСКОМ: убедись, что никто (parse.py, refresh-runner) сейчас не пишет
-- в БД. Если есть фоновые задачи — останови.
-- =============================================================================

BEGIN;

-- 1) Бэкап-копии на случай отката (DROP их потом сам, когда убедишься, что всё ок).
--    CREATE TABLE ... AS копирует данные, но НЕ переносит индексы и FK — это
--    как раз то, что нужно для аварийного «снимка».
CREATE TABLE IF NOT EXISTS posts_backup_20260429    AS TABLE posts;
CREATE TABLE IF NOT EXISTS comments_backup_20260429 AS TABLE comments;

-- 2) Очистка дублей в posts по (group_id, vk_post_id).
--    Оставляем запись с максимальным id (== вставленную позже == с более
--    свежими счётчиками лайков/просмотров).
--    Каскадно подцепится удаление зависимых comments через FK posts->comments.
WITH ranked AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY group_id, vk_post_id
            ORDER BY id DESC
        ) AS rn
    FROM posts
)
DELETE FROM posts
WHERE id IN (SELECT id FROM ranked WHERE rn > 1);

-- 3) Очистка дублей в comments по (post_id, vk_comment_id).
WITH ranked AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY post_id, vk_comment_id
            ORDER BY id DESC
        ) AS rn
    FROM comments
)
DELETE FROM comments
WHERE id IN (SELECT id FROM ranked WHERE rn > 1);

-- 4) Если в схеме случайно остались "ошмётки" старых одиночных UNIQUE
--    на vk_post_id / vk_comment_id — снимаем их.
--    IF EXISTS делает запрос идемпотентным.
ALTER TABLE posts    DROP CONSTRAINT IF EXISTS posts_vk_post_id_key;
ALTER TABLE comments DROP CONSTRAINT IF EXISTS comments_vk_comment_id_key;

DROP INDEX IF EXISTS posts_vk_post_id_key;
DROP INDEX IF EXISTS comments_vk_comment_id_key;
DROP INDEX IF EXISTS uq_posts_vk_post_id;
DROP INDEX IF EXISTS uq_comments_vk_comment_id;

-- 5) Composite UNIQUE — главное.
ALTER TABLE posts
    ADD CONSTRAINT uq_posts_group_vk_post
    UNIQUE (group_id, vk_post_id);

ALTER TABLE comments
    ADD CONSTRAINT uq_comments_post_vk_comment
    UNIQUE (post_id, vk_comment_id);

-- 6) Контрольная проверка.
--    После COMMIT-а можешь руками выполнить:
--      \d posts
--      \d comments
--    и убедиться, что в "Indexes" есть uq_posts_group_vk_post и
--    uq_comments_post_vk_comment.

COMMIT;

-- =============================================================================
-- Когда убедишься, что parse.py отрабатывает чисто, удали бэкапы:
--   DROP TABLE posts_backup_20260429;
--   DROP TABLE comments_backup_20260429;
-- =============================================================================
