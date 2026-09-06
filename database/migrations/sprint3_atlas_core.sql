BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'workers'
    ) THEN
        CREATE TABLE public.workers (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT,
            worker_type TEXT,
            platform TEXT,
            status TEXT DEFAULT 'offline',
            capabilities JSONB DEFAULT '[]'::jsonb,
            created_at TIMESTAMP DEFAULT now(),
            state TEXT CHECK (state IN ('idle', 'working', 'waiting_for_human', 'failed', 'completed'))
        );
    ELSE
        ALTER TABLE public.workers
            ADD COLUMN IF NOT EXISTS state TEXT;

        ALTER TABLE public.workers
            DROP CONSTRAINT IF EXISTS workers_state_check;

        ALTER TABLE public.workers
            ADD CONSTRAINT workers_state_check
            CHECK (state IS NULL OR state IN ('idle', 'working', 'waiting_for_human', 'failed', 'completed'));
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'missions'
    ) THEN
        CREATE TABLE public.missions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            title TEXT NOT NULL,
            description TEXT,
            assigned_worker UUID REFERENCES public.workers(id) ON DELETE SET NULL,
            priority TEXT DEFAULT 'normal',
            status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'active', 'completed', 'failed')),
            progress INTEGER DEFAULT 0 CHECK (progress >= 0 AND progress <= 100),
            result JSONB DEFAULT '{}'::jsonb,
            retry_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT now(),
            updated_at TIMESTAMP DEFAULT now(),
            target_products INT,
            target_pins INT,
            campaign_name TEXT
        );
    ELSE
        ALTER TABLE public.missions
            ADD COLUMN IF NOT EXISTS target_products INT,
            ADD COLUMN IF NOT EXISTS target_pins INT,
            ADD COLUMN IF NOT EXISTS campaign_name TEXT,
            ADD COLUMN IF NOT EXISTS progress INT DEFAULT 0;

        ALTER TABLE public.missions
            ALTER COLUMN status SET DEFAULT 'pending';

        ALTER TABLE public.missions
            DROP CONSTRAINT IF EXISTS missions_status_check;

        ALTER TABLE public.missions
            ADD CONSTRAINT missions_status_check
            CHECK (status IS NULL OR status IN ('pending', 'active', 'completed', 'failed'));
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.mission_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id UUID REFERENCES public.missions(id),
    step_name TEXT,
    worker_role TEXT,
    status TEXT CHECK (status IN ('pending', 'assigned', 'in_progress', 'completed', 'failed')),
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.atlas_commands (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    command_type TEXT CHECK (command_type IN ('CREATE_MISSION', 'START_RESEARCH', 'START_CONTENT', 'START_PUBLISH', 'START_ANALYTICS', 'PAUSE', 'RESUME', 'RETRY')),
    target_worker TEXT,
    mission_id UUID REFERENCES public.missions(id),
    payload JSONB,
    status TEXT CHECK (status IN ('queued', 'sent', 'acknowledged', 'completed', 'failed')),
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.worker_responses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    response_type TEXT CHECK (response_type IN ('MISSION_ACCEPTED', 'MISSION_COMPLETED', 'MISSION_FAILED', 'WAITING_FOR_HUMAN', 'PROGRESS_UPDATE', 'ERROR')),
    worker_id UUID REFERENCES public.workers(id),
    mission_id UUID REFERENCES public.missions(id),
    command_id UUID REFERENCES public.atlas_commands(id),
    payload JSONB,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.identity_vault (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_name TEXT,
    account_type TEXT,
    api_key_encrypted TEXT,
    preferences JSONB,
    verification_status TEXT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.memory_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category TEXT CHECK (category IN ('offer', 'keyword', 'title', 'timing', 'campaign', 'failure')),
    content JSONB,
    score FLOAT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID,
    title TEXT,
    message TEXT,
    type TEXT,
    is_read BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mission_steps_mission_id ON public.mission_steps (mission_id);
CREATE INDEX IF NOT EXISTS idx_atlas_commands_status ON public.atlas_commands (status);
CREATE INDEX IF NOT EXISTS idx_worker_responses_command_id ON public.worker_responses (command_id);

COMMIT;
BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'workers'
    ) THEN
        CREATE TABLE public.workers (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT,
            worker_type TEXT,
            platform TEXT,
            status TEXT DEFAULT 'offline',
            capabilities JSONB DEFAULT '[]'::jsonb,
            created_at TIMESTAMP DEFAULT now(),
            state TEXT CHECK (state IN ('idle', 'working', 'waiting_for_human', 'failed', 'completed'))
        );
    ELSE
        ALTER TABLE public.workers
            ADD COLUMN IF NOT EXISTS state TEXT;

        ALTER TABLE public.workers
            DROP CONSTRAINT IF EXISTS workers_state_check;

        ALTER TABLE public.workers
            ADD CONSTRAINT workers_state_check
            CHECK (state IS NULL OR state IN ('idle', 'working', 'waiting_for_human', 'failed', 'completed'));
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'missions'
    ) THEN
        CREATE TABLE public.missions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            title TEXT NOT NULL,
            description TEXT,
            assigned_worker UUID REFERENCES public.workers(id) ON DELETE SET NULL,
            priority TEXT DEFAULT 'normal',
            status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'active', 'completed', 'failed')),
            progress INTEGER DEFAULT 0 CHECK (progress >= 0 AND progress <= 100),
            result JSONB DEFAULT '{}'::jsonb,
            retry_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT now(),
            updated_at TIMESTAMP DEFAULT now(),
            target_products INT,
            target_pins INT,
            campaign_name TEXT
        );
    ELSE
        ALTER TABLE public.missions
            ADD COLUMN IF NOT EXISTS target_products INT,
            ADD COLUMN IF NOT EXISTS target_pins INT,
            ADD COLUMN IF NOT EXISTS campaign_name TEXT,
            ADD COLUMN IF NOT EXISTS progress INT DEFAULT 0;

        ALTER TABLE public.missions
            ALTER COLUMN status SET DEFAULT 'pending';

        ALTER TABLE public.missions
            DROP CONSTRAINT IF EXISTS missions_status_check;

        ALTER TABLE public.missions
            ADD CONSTRAINT missions_status_check
            CHECK (status IS NULL OR status IN ('pending', 'active', 'completed', 'failed'));
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.mission_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id UUID REFERENCES public.missions(id),
    step_name TEXT,
    worker_role TEXT,
    status TEXT CHECK (status IN ('pending', 'assigned', 'in_progress', 'completed', 'failed')),
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.atlas_commands (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    command_type TEXT CHECK (command_type IN ('CREATE_MISSION', 'START_RESEARCH', 'START_CONTENT', 'START_PUBLISH', 'START_ANALYTICS', 'PAUSE', 'RESUME', 'RETRY')),
    target_worker TEXT,
    mission_id UUID REFERENCES public.missions(id),
    payload JSONB,
    status TEXT CHECK (status IN ('queued', 'sent', 'acknowledged', 'completed', 'failed')),
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.worker_responses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    response_type TEXT CHECK (response_type IN ('MISSION_ACCEPTED', 'MISSION_COMPLETED', 'MISSION_FAILED', 'WAITING_FOR_HUMAN', 'PROGRESS_UPDATE', 'ERROR')),
    worker_id UUID REFERENCES public.workers(id),
    mission_id UUID REFERENCES public.missions(id),
    command_id UUID REFERENCES public.atlas_commands(id),
    payload JSONB,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.identity_vault (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_name TEXT,
    account_type TEXT,
    api_key_encrypted TEXT,
    preferences JSONB,
    verification_status TEXT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.memory_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category TEXT CHECK (category IN ('offer', 'keyword', 'title', 'timing', 'campaign', 'failure')),
    content JSONB,
    score FLOAT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID,
    title TEXT,
    message TEXT,
    type TEXT,
    is_read BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mission_steps_mission_id ON public.mission_steps (mission_id);
CREATE INDEX IF NOT EXISTS idx_atlas_commands_status ON public.atlas_commands (status);
CREATE INDEX IF NOT EXISTS idx_worker_responses_command_id ON public.worker_responses (command_id);

COMMIT;
