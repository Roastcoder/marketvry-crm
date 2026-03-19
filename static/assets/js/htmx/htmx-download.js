/**
 * HTMX Download Extension
 * Handles file downloads via HTMX requests
 */
(function() {
    'use strict';

    htmx.defineExtension('download', {
        onEvent: function(name, evt) {
            if (name === "htmx:beforeRequest") {
                // Set responseType to blob for file downloads
                var elt = evt.detail.elt;
                // Check if this element or any parent has hx-ext="download"
                var hasDownloadExt = false;
                var current = elt;
                while (current) {
                    if (current.hasAttribute && current.hasAttribute('hx-ext')) {
                        var extValue = current.getAttribute('hx-ext');
                        if (extValue && (extValue === 'download' || extValue.includes('download'))) {
                            hasDownloadExt = true;
                            break;
                        }
                    }
                    current = current.parentElement;
                }

                if (hasDownloadExt && evt.detail.xhr) {
                    // Set responseType to blob
                    evt.detail.xhr.responseType = 'blob';

                    // Intercept the onload event to handle download before HTMX processes it
                    var xhr = evt.detail.xhr;
                    var originalOnload = xhr.onload;

                    xhr.onload = function() {
                        // Check for HX-Refresh header first
                        var hxRefresh = xhr.getResponseHeader('HX-Refresh');
                        if (hxRefresh === 'true') {
                            window.location.reload();
                            return;
                        }

                        // Check for error status codes (400, 500, etc)
                        if (xhr.status >= 400) {
                            // Reload page on error
                            window.location.reload();
                            return;
                        }

                        // Check if this is a download response (successful with Content-Disposition)
                        if (xhr.status >= 200 && xhr.status < 300) {
                            var contentDisposition = xhr.getResponseHeader('Content-Disposition');
                            if (contentDisposition && contentDisposition.indexOf('attachment') !== -1) {
                                // This is a download - handle it immediately
                                var blob = xhr.response;

                                // Verify it's a blob
                                if (!(blob instanceof Blob)) {
                                    console.error('Download extension: Expected Blob but got:', typeof blob);
                                    var contentType = xhr.getResponseHeader('Content-Type') || 'application/octet-stream';
                                    blob = new Blob([xhr.response], { type: contentType });
                                }

                                var url = window.URL.createObjectURL(blob);

                                // Extract filename from Content-Disposition header
                                var filename = 'download';
                                var filenameMatch = contentDisposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
                                if (filenameMatch && filenameMatch[1]) {
                                    filename = filenameMatch[1].replace(/['"]/g, '');
                                    // Handle UTF-8 encoded filenames
                                    if (filename.startsWith('UTF-8\'\'')) {
                                        filename = decodeURIComponent(filename.replace(/^UTF-8''/, ''));
                                    }
                                }

                                // Create a temporary anchor element and trigger download
                                var a = document.createElement('a');
                                a.href = url;
                                a.download = filename;
                                a.style.display = 'none';
                                document.body.appendChild(a);
                                a.click();

                                // Clean up
                                setTimeout(function() {
                                    if (document.body.contains(a)) {
                                        document.body.removeChild(a);
                                    }
                                    window.URL.revokeObjectURL(url);
                                }, 100);

                                // Mark that we handled this download
                                xhr._downloadHandled = true;

                                // Call original onload
                                if (originalOnload) {
                                    originalOnload.call(this);
                                }
                                return;
                            }
                        }

                        // Not a download, proceed normally
                        if (originalOnload) {
                            originalOnload.call(this);
                        }
                    };

                    // Also handle network errors
                    var originalOnerror = xhr.onerror;
                    xhr.onerror = function() {
                        window.location.reload();
                        if (originalOnerror) {
                            originalOnerror.call(this);
                        }
                    };
                }
            }

            if (name === "htmx:beforeSwap") {
                // Prevent HTMX from swapping blob responses for downloads
                var xhr = evt.detail.xhr;
                if (xhr && xhr.responseType === 'blob') {
                    var contentDisposition = xhr.getResponseHeader('Content-Disposition');
                    if (contentDisposition && contentDisposition.indexOf('attachment') !== -1) {
                        // Prevent swapping for downloads
                        evt.detail.shouldSwap = false;
                        return false;
                    }
                }
            }
        },

        transformResponse: function(text, xhr, elt) {
            // Don't transform blob responses
            if (xhr && xhr.responseType === 'blob') {
                return '';
            }
            // Don't transform the response if it's a download
            var contentDisposition = xhr.getResponseHeader('Content-Disposition');
            if (contentDisposition && contentDisposition.indexOf('attachment') !== -1) {
                return '';
            }
            return text;
        }
    });
})();
// /**
//  * HTMX Download Extension
//  * Handles file downloads via HTMX requests
//  */
// (function() {
//     'use strict';

//     htmx.defineExtension('download', {
//         onEvent: function(name, evt) {
//             if (name === "htmx:beforeRequest") {
//                 // Set responseType to blob for file downloads
//                 var elt = evt.detail.elt;
//                 // Check if this element or any parent has hx-ext="download"
//                 var hasDownloadExt = false;
//                 var current = elt;
//                 while (current) {
//                     if (current.hasAttribute && current.hasAttribute('hx-ext')) {
//                         var extValue = current.getAttribute('hx-ext');
//                         if (extValue && (extValue === 'download' || extValue.includes('download'))) {
//                             hasDownloadExt = true;
//                             break;
//                         }
//                     }
//                     current = current.parentElement;
//                 }

//                 if (hasDownloadExt && evt.detail.xhr) {
//                     // Set responseType to blob
//                     evt.detail.xhr.responseType = 'blob';

//                     // Intercept the onload event to handle download before HTMX processes it
//                     var xhr = evt.detail.xhr;
//                     var originalOnload = xhr.onload;

//                     xhr.onload = function() {
//                         // Check if this is a download response
//                         if (xhr.status >= 200 && xhr.status < 300) {
//                             var contentDisposition = xhr.getResponseHeader('Content-Disposition');
//                             if (contentDisposition && contentDisposition.indexOf('attachment') !== -1) {
//                                 // This is a download - handle it immediately
//                                 // Use the blob directly from xhr.response - it should already be a Blob
//                                 var blob = xhr.response;

//                                 // Verify it's a blob, if not, something went wrong
//                                 if (!(blob instanceof Blob)) {
//                                     console.error('Download extension: Expected Blob but got:', typeof blob);
//                                     // Try to create blob from response
//                                     var contentType = xhr.getResponseHeader('Content-Type') || 'application/octet-stream';
//                                     blob = new Blob([xhr.response], { type: contentType });
//                                 }

//                                 var url = window.URL.createObjectURL(blob);

//                                 // Extract filename from Content-Disposition header
//                                 var filename = 'download';
//                                 var filenameMatch = contentDisposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
//                                 if (filenameMatch && filenameMatch[1]) {
//                                     filename = filenameMatch[1].replace(/['"]/g, '');
//                                     // Handle UTF-8 encoded filenames
//                                     if (filename.startsWith('UTF-8\'\'')) {
//                                         filename = decodeURIComponent(filename.replace(/^UTF-8''/, ''));
//                                     }
//                                 }

//                                 // Create a temporary anchor element and trigger download
//                                 var a = document.createElement('a');
//                                 a.href = url;
//                                 a.download = filename;
//                                 a.style.display = 'none';
//                                 document.body.appendChild(a);
//                                 a.click();

//                                 // Clean up
//                                 setTimeout(function() {
//                                     if (document.body.contains(a)) {
//                                         document.body.removeChild(a);
//                                     }
//                                     window.URL.revokeObjectURL(url);
//                                 }, 100);

//                                 // Mark that we handled this download
//                                 xhr._downloadHandled = true;

//                                 // Call original onload - HTMX will process but we'll prevent swap in beforeSwap
//                                 if (originalOnload) {
//                                     originalOnload.call(this);
//                                 }
//                                 return;
//                             }
//                         }

//                         // Not a download, proceed normally
//                         if (originalOnload) {
//                             originalOnload.call(this);
//                         }
//                     };
//                 }
//             }

//             if (name === "htmx:beforeSwap") {
//                 // Prevent HTMX from swapping blob responses
//                 var xhr = evt.detail.xhr;
//                 if (xhr && xhr.responseType === 'blob') {
//                     var contentDisposition = xhr.getResponseHeader('Content-Disposition');
//                     if (contentDisposition && contentDisposition.indexOf('attachment') !== -1) {
//                         // Prevent swapping for downloads
//                         evt.detail.shouldSwap = false;
//                         return false;
//                     }
//                 }
//             }
//         },

//         transformResponse: function(text, xhr, elt) {
//             // Don't transform blob responses - they're binary data
//             if (xhr && xhr.responseType === 'blob') {
//                 return '';
//             }
//             // Don't transform the response if it's a download
//             var contentDisposition = xhr.getResponseHeader('Content-Disposition');
//             if (contentDisposition && contentDisposition.indexOf('attachment') !== -1) {
//                 return '';
//             }
//             return text;
//         }
//     });
// })();
