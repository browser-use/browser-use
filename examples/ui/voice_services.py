"""
Serviços de voz para transcrição (STT) e síntese (TTS).

Integra com:
- OpenAI Whisper API para Speech-to-Text
- OpenAI TTS API para Text-to-Speech
"""

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

import openai

logger = logging.getLogger(__name__)


class VoiceServices:
    """Fornece serviços de transcrição e síntese de voz"""
    
    def __init__(self):
        """Inicializa serviços de voz"""
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        if not self.openai_api_key:
            logger.warning("OPENAI_API_KEY não configurada - serviços de voz não disponíveis")
        
        self.client = openai.AsyncOpenAI(api_key=self.openai_api_key) if self.openai_api_key else None
    
    async def transcribe_audio(self, audio_bytes: bytes, filename: str = "audio.webm") -> str:
        """
        Transcreve áudio para texto usando Whisper API.
        
        Args:
            audio_bytes: Bytes do arquivo de áudio
            filename: Nome do arquivo (para determinar formato)
            
        Returns:
            Texto transcrito
            
        Raises:
            ValueError: Se API key não configurada
            Exception: Erros da API
        """
        if not self.client:
            raise ValueError("OpenAI API key não configurada")
        
        try:
            # Salvar temporariamente o áudio
            with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix, delete=False) as temp_file:
                temp_file.write(audio_bytes)
                temp_path = temp_file.name
            
            try:
                # Transcrever usando Whisper
                with open(temp_path, "rb") as audio_file:
                    transcript = await self.client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file,
                        language="pt"  # Português como padrão, pode ser configurável
                    )
                
                logger.info(f"Áudio transcrito com sucesso: {transcript.text[:100]}...")
                return transcript.text
                
            finally:
                # Remover arquivo temporário
                Path(temp_path).unlink(missing_ok=True)
                
        except Exception as e:
            logger.error(f"Erro ao transcrever áudio: {e}")
            raise
    
    async def synthesize_speech(
        self,
        text: str,
        voice: str = "alloy",
        model: str = "tts-1",
        speed: float = 1.0
    ) -> bytes:
        """
        Converte texto em fala usando TTS API.
        
        Args:
            text: Texto a ser sintetizado
            voice: Voz a usar (alloy, echo, fable, onyx, nova, shimmer)
            model: Modelo TTS (tts-1 ou tts-1-hd)
            speed: Velocidade da fala (0.25 a 4.0)
            
        Returns:
            Bytes do áudio MP3
            
        Raises:
            ValueError: Se API key não configurada
            Exception: Erros da API
        """
        if not self.client:
            raise ValueError("OpenAI API key não configurada")
        
        try:
            # Sintetizar fala
            response = await self.client.audio.speech.create(
                model=model,
                voice=voice,
                input=text,
                speed=speed
            )
            
            # Ler bytes do áudio
            audio_bytes = response.content
            
            logger.info(f"Fala sintetizada com sucesso: {len(audio_bytes)} bytes")
            return audio_bytes
            
        except Exception as e:
            logger.error(f"Erro ao sintetizar fala: {e}")
            raise
    
    async def transcribe_audio_with_timestamps(
        self,
        audio_bytes: bytes,
        filename: str = "audio.webm"
    ) -> dict:
        """
        Transcreve áudio com timestamps detalhados.
        
        Args:
            audio_bytes: Bytes do arquivo de áudio
            filename: Nome do arquivo
            
        Returns:
            Dict com texto e timestamps
        """
        if not self.client:
            raise ValueError("OpenAI API key não configurada")
        
        try:
            # Salvar temporariamente o áudio
            with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix, delete=False) as temp_file:
                temp_file.write(audio_bytes)
                temp_path = temp_file.name
            
            try:
                # Transcrever com timestamps
                with open(temp_path, "rb") as audio_file:
                    transcript = await self.client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file,
                        language="pt",
                        response_format="verbose_json",
                        timestamp_granularities=["word", "segment"]
                    )
                
                return {
                    "text": transcript.text,
                    "language": transcript.language,
                    "duration": transcript.duration,
                    "words": transcript.words if hasattr(transcript, 'words') else [],
                    "segments": transcript.segments if hasattr(transcript, 'segments') else []
                }
                
            finally:
                # Remover arquivo temporário
                Path(temp_path).unlink(missing_ok=True)
                
        except Exception as e:
            logger.error(f"Erro ao transcrever áudio com timestamps: {e}")
            raise


# Vozes disponíveis na OpenAI TTS
AVAILABLE_VOICES = {
    "alloy": "Voz neutra e equilibrada",
    "echo": "Voz masculina clara",
    "fable": "Voz britânica expressiva",
    "onyx": "Voz masculina profunda",
    "nova": "Voz feminina energética",
    "shimmer": "Voz feminina suave"
}
