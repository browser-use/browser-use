-- Migration script that checks for existing tables before creating

DO $$
BEGIN
    -- Check if tables already exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'tasks') THEN
        -- Create tasks table
        CREATE TABLE tasks (
            id SERIAL PRIMARY KEY,
            task VARCHAR NOT NULL,
            config JSONB,
            status VARCHAR NOT NULL,
            result JSONB,
            error VARCHAR,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            started_at TIMESTAMP WITH TIME ZONE,
            completed_at TIMESTAMP WITH TIME ZONE
        );

        -- Create index for tasks
        CREATE INDEX idx_tasks_status ON tasks(status);
        CREATE INDEX idx_tasks_created_at ON tasks(created_at);
        
        RAISE NOTICE 'Created tasks table';
    ELSE
        RAISE NOTICE 'tasks table already exists, skipping creation';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'metrics') THEN
        -- Create metrics table
        CREATE TABLE metrics (
            id SERIAL PRIMARY KEY,
            name VARCHAR NOT NULL,
            value DOUBLE PRECISION NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        );

        -- Create index for metrics
        CREATE INDEX idx_metrics_name ON metrics(name);
        CREATE INDEX idx_metrics_created_at ON metrics(created_at);
        
        RAISE NOTICE 'Created metrics table';
    ELSE
        RAISE NOTICE 'metrics table already exists, skipping creation';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'sessions') THEN
        -- Create sessions table
        CREATE TABLE sessions (
            id SERIAL PRIMARY KEY,
            task_id INTEGER NOT NULL,
            start_time TIMESTAMP WITH TIME ZONE NOT NULL,
            end_time TIMESTAMP WITH TIME ZONE,
            status VARCHAR NOT NULL,
            error VARCHAR,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        );

        -- Create index for sessions
        CREATE INDEX idx_sessions_task_id ON sessions(task_id);
        CREATE INDEX idx_sessions_status ON sessions(status);
        CREATE INDEX idx_sessions_start_time ON sessions(start_time);
        
        RAISE NOTICE 'Created sessions table';
    ELSE
        RAISE NOTICE 'sessions table already exists, skipping creation';
    END IF;
END $$;

-- Output the results
SELECT 'Migration completed with existence checks' AS result;