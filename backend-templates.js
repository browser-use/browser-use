const express = require('express');
const puppeteer = require('puppeteer');

const app = express();
app.use(express.json());

let tasks = {};

// Route to create a new browser automation task
app.post('/tasks', async (req, res) => {
    const { url } = req.body;
    if (!url) {
        return res.status(400).json({ message: 'URL is required.' });
    }
    const taskId = Date.now();
    tasks[taskId] = { status: 'running', result: null };

    try {
        const browser = await puppeteer.launch();
        const page = await browser.newPage();
        await page.goto(url);
        tasks[taskId].result = await page.content();
        tasks[taskId].status = 'completed';
        await browser.close();
    } catch (error) {
        tasks[taskId].status = 'failed';
        tasks[taskId].result = error.message;
    }
    res.status(201).json({ taskId });
});

// Route to check task status
app.get('/tasks/:id', (req, res) => {
    const { id } = req.params;
    const task = tasks[id];
    if (!task) {
        return res.status(404).json({ message: 'Task not found.' });
    }
    res.json(task);
});

// Route to fetch task result
app.get('/tasks/:id/result', (req, res) => {
    const { id } = req.params;
    const task = tasks[id];
    if (!task) {
        return res.status(404).json({ message: 'Task not found.' });
    }
    if (task.status !== 'completed') {
        return res.status(400).json({ message: 'Task is not yet completed.' });
    }
    res.json({ result: task.result });
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(`Server is running on port ${PORT}`);
});
