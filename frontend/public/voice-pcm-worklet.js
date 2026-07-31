// AudioWorkletProcessor that converts Float32 mic samples to Int16 PCM and posts them
// back to the main thread in ~20ms chunks over its MessagePort. Loaded directly as a
// static file via audioContext.audioWorklet.addModule("/voice-pcm-worklet.js") — an
// AudioWorklet module must be fetched by URL, it can't be bundled through webpack like
// the rest of the app's JS.
class VoicePcmProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buffer = [];
    this._bufferedSamples = 0;
    this._chunkSamples = 320; // ~20ms at 16kHz — matches useVoiceSocket.ts's SAMPLE_RATE
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel && channel.length) {
      const int16 = new Int16Array(channel.length);
      for (let i = 0; i < channel.length; i++) {
        const s = Math.max(-1, Math.min(1, channel[i]));
        int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
      }
      this._buffer.push(int16);
      this._bufferedSamples += int16.length;

      if (this._bufferedSamples >= this._chunkSamples) {
        const merged = new Int16Array(this._bufferedSamples);
        let offset = 0;
        for (const chunk of this._buffer) {
          merged.set(chunk, offset);
          offset += chunk.length;
        }
        this._buffer = [];
        this._bufferedSamples = 0;
        this.port.postMessage(merged.buffer, [merged.buffer]);
      }
    }
    return true; // keep the processor alive for the life of the mic session
  }
}

registerProcessor("voice-pcm-processor", VoicePcmProcessor);
