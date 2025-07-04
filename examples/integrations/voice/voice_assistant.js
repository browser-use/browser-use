/* Simple browser voice assistant demo */

const jarvis = {
    // Speak a message using the Web Speech API
    whisper(text) {
        const utter = new SpeechSynthesisUtterance(text);
        window.speechSynthesis.speak(utter);
    },

    // Alias for backwards compatibility
    speak(text) {
        jarvis.whisper(text);
    },

    // Greet the user based on the current time
    wishUser() {
        const hour = new Date().getHours();
        if (hour < 12) {
            jarvis.speak('Bom dia!');
        } else if (hour < 18) {
            jarvis.speak('Boa tarde!');
        } else {
            jarvis.speak('Boa noite!');
        }
    },

    recognition: null,

    initRecognition() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (SpeechRecognition) {
            jarvis.recognition = new SpeechRecognition();
            jarvis.recognition.lang = 'pt-BR';
            jarvis.recognition.onresult = event => {
                const command = event.results[0][0].transcript.toLowerCase();
                jarvis.handleCommand(command);
            };
        }
    },

    listenCommand() {
        if (!jarvis.recognition) {
            alert('Speech recognition not supported in this browser.');
            return;
        }
        jarvis.recognition.start();
    },

    // Respond to known commands or search the web
    handleCommand(cmd) {
        if (cmd.includes('hora')) {
            const now = new Date();
            jarvis.speak(`Agora são ${now.getHours()} horas e ${now.getMinutes()} minutos.`);
        } else if (cmd.includes('olá') || cmd.includes('oi')) {
            jarvis.speak('Olá! Como posso ajudar?');
        } else {
            window.open(`https://www.google.com/search?q=${encodeURIComponent(cmd)}`, '_blank');
        }
    },

    init() {
        jarvis.initRecognition();
        window.addEventListener('load', () => {
            jarvis.speak('inicializando o Jarvis chatbot');
            jarvis.wishUser();
        });
        document.addEventListener('DOMContentLoaded', () => {
            const btn = document.getElementById('voice-button');
            if (btn) {
                btn.addEventListener('click', jarvis.listenCommand);
            }
        });
    },
};

jarvis.init();
