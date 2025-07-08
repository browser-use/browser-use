/* Simple browser voice assistant demo */

// Speak a message using the Web Speech API
function speak(text) {
    const utter = new SpeechSynthesisUtterance(text);
    window.speechSynthesis.speak(utter);
}

// Greet the user based on the current time
function wishUser() {
    const hour = new Date().getHours();
    if (hour < 12) {
        speak('Bom dia!');
    } else if (hour < 18) {
        speak('Boa tarde!');
    } else {
        speak('Boa noite!');
    }
}

// Listen for a voice command and handle the result
function listenCommand() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        alert('Speech recognition not supported in this browser.');
        return;
    }
    const recognition = new SpeechRecognition();
    recognition.lang = 'pt-BR';
    recognition.onresult = event => {
        const command = event.results[0][0].transcript.toLowerCase();
        handleCommand(command);
    };
    recognition.start();
}

// Respond to known commands or search the web
function handleCommand(cmd) {
    if (cmd.includes('hora')) {
        const now = new Date();
        speak(`Agora são ${now.getHours()} horas e ${now.getMinutes()} minutos.`);
    } else if (cmd.includes('olá') || cmd.includes('oi')) {
        speak('Olá! Como posso ajudar?');
    } else {
        window.open(`https://www.google.com/search?q=${encodeURIComponent(cmd)}`, '_blank');
    }
}

window.addEventListener('load', () => {
    speak('inicializando o Jarvis chatbot');
    wishUser();
});

// Example: attach listener to a button with id "voice-button"
document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('voice-button');
    if (btn) {
        btn.addEventListener('click', listenCommand);
    }
});
