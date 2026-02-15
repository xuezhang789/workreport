class UploadManager {
    constructor(options = {}) {
        this.options = options; // Store options
        this.chunkSize = options.chunkSize || 2 * 1024 * 1024; // 2MB
        this.maxSize = options.maxSize || 50 * 1024 * 1024; // 50MB
        this.api = {
            init: '/core/api/upload/init/',
            chunk: '/core/api/upload/chunk/',
            complete: '/core/api/upload/complete/',
            ...options.api
        };
        this.onProgress = options.onProgress || (() => {});
        this.onSuccess = options.onSuccess || (() => {});
        this.onError = options.onError || (() => {});
        this.maxRetries = 3;
        this.compress = options.compress || false; // Enable compression
    }

    validate(file) {
        if (file.size > this.maxSize) {
            return `File too large (Max ${this.maxSize / 1024 / 1024}MB)`;
        }
        return null;
    }

    async upload(file) {
        let fileToUpload = file;
        
        // Compression
        if (this.compress && file.type.startsWith('image/')) {
            try {
                fileToUpload = await this.compressImage(file);
            } catch (e) {
                console.warn('Compression failed, uploading original:', e);
            }
        }

        const error = this.validate(fileToUpload);
        if (error) {
            this.onError(fileToUpload, error);
            throw new Error(error);
        }

        // Always use chunked upload for consistency
        return this.uploadChunked(fileToUpload);
    }

    async compressImage(file, quality = 0.8, maxWidth = 1920) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.readAsDataURL(file);
            reader.onload = (event) => {
                const img = new Image();
                img.src = event.target.result;
                img.onload = () => {
                    const canvas = document.createElement('canvas');
                    let width = img.width;
                    let height = img.height;

                    if (width > maxWidth) {
                        height = Math.round(height * (maxWidth / width));
                        width = maxWidth;
                    }

                    canvas.width = width;
                    canvas.height = height;
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(img, 0, 0, width, height);

                    canvas.toBlob((blob) => {
                        if (!blob) {
                            reject(new Error('Canvas is empty'));
                            return;
                        }
                        // Create a new File object with proper name and type
                        const newFile = new File([blob], file.name, {
                            type: file.type,
                            lastModified: Date.now(),
                        });
                        resolve(newFile);
                    }, file.type, quality);
                };
                img.onerror = (error) => reject(error);
            };
            reader.onerror = (error) => reject(error);
        });
    }

    async uploadChunked(file) {
        try {
            // 1. Init
            const initRes = await this.postJson(this.api.init, {
                filename: file.name,
                size: file.size,
                type: this.options.type || 'default' // Pass upload type
            });
            if (initRes.status !== 'success') throw new Error(initRes.message);
            
            const uploadId = initRes.upload_id;
            const uploadedSize = initRes.uploaded_size || 0; // Resume support

            // 2. Chunks
            const totalChunks = Math.ceil(file.size / this.chunkSize);
            for (let i = 0; i < totalChunks; i++) {
                const start = i * this.chunkSize;
                const end = Math.min(start + this.chunkSize, file.size);

                // Skip if already uploaded (Resume)
                if (start < uploadedSize) {
                    const progress = Math.round(((i + 1) / totalChunks) * 100);
                    this.onProgress(file, progress);
                    continue;
                }

                const chunk = file.slice(start, end);
                await this.uploadChunkWithRetry(uploadId, i, start, chunk);

                // Progress
                const progress = Math.round(((i + 1) / totalChunks) * 100);
                this.onProgress(file, progress);
            }

            // 3. Complete
            const completeRes = await this.postJson(this.api.complete, { upload_id: uploadId });
            if (completeRes.status !== 'success') throw new Error(completeRes.message);

            this.onSuccess(file, { upload_id: uploadId });
            return { upload_id: uploadId };

        } catch (e) {
            this.onError(file, e.message);
            throw e;
        }
    }

    async uploadChunkWithRetry(uploadId, chunkIndex, offset, chunkBlob) {
        let lastError;
        for (let attempt = 0; attempt < this.maxRetries; attempt++) {
            try {
                const formData = new FormData();
                formData.append('upload_id', uploadId);
                formData.append('chunk_index', chunkIndex);
                formData.append('offset', offset);
                formData.append('file', chunkBlob);

                const res = await this.postForm(this.api.chunk, formData);
                if (res.status === 'success') return;
                
                throw new Error(res.message || 'Chunk upload failed');
            } catch (e) {
                lastError = e;
                console.warn(`Chunk ${chunkIndex} attempt ${attempt + 1} failed: ${e.message}`);
                // Simple backoff
                await new Promise(r => setTimeout(r, 1000 * (attempt + 1)));
            }
        }
        throw lastError;
    }

    // Helpers
    async postJson(url, data) {
        const csrfToken = this.getCsrfToken();
        const headers = {
            'Content-Type': 'application/json'
        };
        if (csrfToken) {
            headers['X-CSRFToken'] = csrfToken;
        }
        
        const res = await fetch(url, {
            method: 'POST',
            headers: headers,
            body: JSON.stringify(data)
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
    }

    async postForm(url, formData) {
        const csrfToken = this.getCsrfToken();
        const headers = {};
        if (csrfToken) {
            headers['X-CSRFToken'] = csrfToken;
        }

        const res = await fetch(url, {
            method: 'POST',
            headers: headers,
            body: formData
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
    }

    getCsrfToken() {
        return document.querySelector('[name=csrfmiddlewaretoken]')?.value || 
               document.querySelector('meta[name="csrf-token"]')?.content ||
               '';
    }
}

window.UploadManager = UploadManager;