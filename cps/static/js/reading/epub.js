/* global $, calibre, EPUBJS, ePubReader */

var reader;

(function () {
    "use strict";

    EPUBJS.filePath = calibre.filePath;
    EPUBJS.cssPath = calibre.cssPath;

    reader = ePubReader(calibre.bookUrl, {
        restore: true,
        bookmarks: calibre.bookmark ? [calibre.bookmark] : [],
    });

    // Allow scripts inside the book content iframe.
    //
    // epub.js (epub.min.js, IframeView.create) builds the content iframe with
    // `sandbox="allow-same-origin"` and only appends `allow-scripts` when
    // `settings.allowScriptedContent` is true (it defaults to false). Without
    // it, books whose pages rely on <script> (many covers do) throw
    //   Blocked script execution in 'about:srcdoc' because the document's
    //   frame is sandboxed and the 'allow-scripts' permission is not set.
    // and the page renders broken (e.g. the themed background/text colors the
    // user picked end up wrong).
    //
    // Chrome additionally warns (and rightfully so) that a sandbox carrying
    // BOTH allow-scripts AND allow-same-origin can be escaped by the framed
    // content, so instead of adding allow-scripts we patch epub.min.js to
    // REMOVE the sandbox attribute entirely whenever allowScriptedContent is
    // enabled (see IframeView.create). Without a sandbox attribute, a srcdoc
    // document keeps the parent origin, so the parent can still drive the
    // iframe DOM (themes, layout, marks) and the book's own scripts run —
    // with no sandbox warning. Security trade-off: book scripts get full
    // access to the reader page (acceptable for a personal library).
    //
    // epub.js renders asynchronously (display() is queued), so patching the
    // settings here — right after ePubReader() returns and before the first
    // iframe is created — is safe. We patch both the rendition settings and
    // the already-constructed manager's viewSettings (IframeView receives a
    // copy of viewSettings, not a live reference).
    try {
        if (reader.rendition) {
            reader.rendition.settings.allowScriptedContent = true;
            if (
                reader.rendition.manager &&
                reader.rendition.manager.viewSettings
            ) {
                reader.rendition.manager.viewSettings.allowScriptedContent =
                    true;
            }
        }
    } catch (e) {
        console.error("Failed to enable allowScriptedContent", e);
    }

    Object.keys(themes).forEach(function (theme) {
        reader.rendition.themes.register(theme, themes[theme].css_path);
    });

    if (calibre.useBookmarks) {
        reader.on("reader:bookmarked", updateBookmark.bind(reader, "add"));
        reader.on("reader:unbookmarked", updateBookmark.bind(reader, "remove"));
    } else {
        $("#bookmark, #show-Bookmarks").remove();
    }

    // Enable swipe support
    // I have no idea why swiperRight/swiperLeft from plugins is not working, events just don't get fired
    var touchStart = 0;
    var touchEnd = 0;

    reader.rendition.on('touchstart', function(event) {
        touchStart = event.changedTouches[0].screenX;
    });
    reader.rendition.on('touchend', function(event) {
      touchEnd = event.changedTouches[0].screenX;
        if (touchStart < touchEnd) {
            if(reader.book.package.metadata.direction === "rtl") {
    			reader.rendition.next();
    		} else {
    			reader.rendition.prev();
    		}
            // Swiped Right
        }
        if (touchStart > touchEnd) {
            if(reader.book.package.metadata.direction === "rtl") {
    			reader.rendition.prev();
    		} else {
                reader.rendition.next();
    		}
            // Swiped Left
        }
    });

    // Update progress percentage
    let progressDiv = document.getElementById("progress");
    // Pages counter (virtual pages via EPUB locations)
    let pagesDiv = document.getElementById("pages-count");
    // Honor saved visibility preference for pages counter
    (function () {
        try {
            var pref = localStorage.getItem("calibre.reader.showPages");
            var show = pref === null ? true : pref === "true";
            if (pagesDiv)
                pagesDiv.style.visibility = show ? "visible" : "hidden";
        } catch (e) {}
    })();

    // --- Reading progress auto-save (throttled) ---
    var lastSavedCfi = null;
    var lastSavedPercentage = -1;
    var lastSaveTime = 0;
    var SAVE_THROTTLE_MS = 5000;
    var pendingCfi = null;
    var pendingPercentage = null;
    var saveTimer = null;

    function getCsrfToken() {
        return $("input[name='csrf_token']").val();
    }

    function saveProgressToBackend(cfi, percentage) {
        if (!calibre.bookmarkUrl) return;
        var csrftoken = getCsrfToken();
        var percentStr = (Math.round(percentage * 1000) / 10).toString();
        $.ajax(calibre.bookmarkUrl, {
            method: "post",
            data: {
                bookmark: cfi || "",
                progress_percent: percentStr,
            },
            headers: { "X-CSRFToken": csrftoken },
        }).done(function () {
            lastSavedCfi = cfi;
            lastSavedPercentage = percentage;
        });
    }

    function throttledSaveProgress(cfi, percentage) {
        pendingCfi = cfi;
        pendingPercentage = percentage;
        var now = Date.now();
        var elapsed = now - lastSaveTime;
        if (elapsed >= SAVE_THROTTLE_MS) {
            if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; }
            lastSaveTime = now;
            saveProgressToBackend(pendingCfi, pendingPercentage);
        } else if (!saveTimer) {
            saveTimer = setTimeout(function () {
                saveTimer = null;
                lastSaveTime = Date.now();
                saveProgressToBackend(pendingCfi, pendingPercentage);
            }, SAVE_THROTTLE_MS - elapsed);
        }
    }

    function flushProgressSave() {
        if (saveTimer) {
            clearTimeout(saveTimer);
            saveTimer = null;
        }
        if (pendingCfi !== null && (pendingCfi !== lastSavedCfi || pendingPercentage !== lastSavedPercentage)) {
            // Use sendBeacon for reliability during page unload
            var percentStr = (Math.round(pendingPercentage * 1000) / 10).toString();
            var csrftoken = getCsrfToken();
            var formData = new FormData();
            formData.append("bookmark", pendingCfi || "");
            formData.append("progress_percent", percentStr);
            formData.append("csrf_token", csrftoken || "");
            if (navigator.sendBeacon && calibre.bookmarkUrl) {
                var blob = new Blob([
                    "bookmark=" + encodeURIComponent(pendingCfi || "") +
                    "&progress_percent=" + encodeURIComponent(percentStr) +
                    "&csrf_token=" + encodeURIComponent(csrftoken || "")
                ], { type: "application/x-www-form-urlencoded" });
                navigator.sendBeacon(calibre.bookmarkUrl, blob);
                lastSavedCfi = pendingCfi;
                lastSavedPercentage = pendingPercentage;
            } else {
                saveProgressToBackend(pendingCfi, pendingPercentage);
            }
        }
    }

    window.addEventListener("beforeunload", flushProgressSave);
    // pagehide is more reliable on mobile browsers
    window.addEventListener("pagehide", flushProgressSave);

    reader.book.ready.then(() => {
        let locations_key = reader.book.key() + "-locations";
        // Key to persist last-read position for this book in localStorage
        let position_key = "calibre.reader.position." + reader.book.key();
        let stored_locations = localStorage.getItem(locations_key);
        let make_locations, save_locations;
        if (stored_locations) {
            make_locations = Promise.resolve(
                reader.book.locations.load(stored_locations)
            );
            // No-op because locations are already saved
            save_locations = () => {};
        } else {
            make_locations = reader.book.locations.generate();
            save_locations = () => {
                localStorage.setItem(
                    locations_key,
                    reader.book.locations.save()
                );
            };
        }
        make_locations
            .then(() => {
                // Try to restore last position (CFI) from localStorage if present
                try {
                    var _savedPos = localStorage.getItem(position_key);
                    if (_savedPos) {
                        try {
                            var _posObj = JSON.parse(_savedPos);
                            if (_posObj && _posObj.cfi) {
                                // Display the saved CFI location
                                try {
                                    reader.rendition.display(_posObj.cfi);
                                } catch (e) {}
                            }
                        } catch (e) {}
                    }
                } catch (e) {}

                reader.rendition.on("relocated", (location) => {
                    // Re-apply the custom theme class to the LIVE <body> of
                    // every content iframe. epub.js's Contents caches the
                    // body reference at creation time (`this.content`) and
                    // never refreshes it; when a view is re-created (e.g.
                    // leaving the cover page and coming back, or any section
                    // whose body gets regenerated) themes.inject() adds the
                    // "customTheme" class to that detached/stale node, so the
                    // visible body misses it and text falls back to the
                    // book's own (black) color. Adding the class straight to
                    // document.body here is cheap and idempotent.
                    try {
                        if (
                            reader.rendition.themes &&
                            reader.rendition.themes._current === "customTheme"
                        ) {
                            reader.rendition.getContents().forEach(
                                function (content) {
                                    if (
                                        content &&
                                        content.document &&
                                        content.document.body
                                    ) {
                                        content.document.body.classList.add(
                                            "customTheme"
                                        );
                                    }
                                }
                            );
                        }
                    } catch (e) {}

                    // Use start.percentage: epub.js's relocated payload defines the
                    // top-level percentage from location.start. location.end.percentage
                    // resolves to 0 for most sections (the end CFI maps outside the
                    // generated locations range), which made the UI always show 0%.
                    let startPct = location.start && location.start.percentage;
                    let percentage = Math.round(
                        (typeof startPct === "number" ? startPct : 0) * 100
                    );
                    progressDiv.textContent = percentage + "%";

                    // Pages based on generated EPUB locations (CFI positions)
                    const cfi = location.start.cfi;
                    const current =
                        reader.book.locations.locationFromCfi(cfi) || 0; // 1-based index typically
                    const total = reader.book.locations.length() || 0;

                    if (total > 0) {
                        pagesDiv.textContent = current + "/" + total;
                        pagesDiv.style.visibility = "visible";
                    } else {
                        pagesDiv.textContent = "";
                        pagesDiv.style.visibility = "hidden";
                    }

                    // Persist last position (CFI + percentage) to localStorage so reader can restore on next open
                    try {
                        var posObj = {
                            cfi: location.start.cfi,
                            percentage: location.start.percentage,
                        };
                        localStorage.setItem(
                            position_key,
                            JSON.stringify(posObj)
                        );
                    } catch (e) {}

                    // Auto-save reading progress to backend (throttled)
                    throttledSaveProgress(location.start.cfi, startPct || 0);
                });
                reader.rendition.reportLocation();
                progressDiv.style.visibility = "visible";
            })
            .then(save_locations);
    });

    /**
     * @param {string} action - Add or remove bookmark
     * @param {string|int} location - Location or zero
     */
    function updateBookmark(action, location) {
        // Remove other bookmarks (there can only be one)
        if (action === "add") {
            this.settings.bookmarks
                .filter(function (bookmark) {
                    return bookmark && bookmark !== location;
                })
                .map(
                    function (bookmark) {
                        this.removeBookmark(bookmark);
                    }.bind(this)
                );
        }

        var csrftoken = $("input[name='csrf_token']").val();

        // Save to database
        $.ajax(calibre.bookmarkUrl, {
            method: "post",
            data: { bookmark: location || "" },
            headers: { "X-CSRFToken": csrftoken },
        }).fail(function (xhr, status, error) {
            alert(error);
        });
    }

    // Default settings load
    const theme = localStorage.getItem("calibre.reader.theme") ?? "lightTheme";
    selectTheme(theme);

    // Restore saved font and font size after reader is ready
    reader.book.ready.then(() => {
        const savedFontSize = localStorage.getItem("calibre.reader.fontSize");
        if (savedFontSize) {
            reader.rendition.themes.fontSize(`${savedFontSize}%`);
        }

        const savedFont = localStorage.getItem("calibre.reader.font");
        if (savedFont && window.selectFont) {
            window.selectFont(savedFont);
        }
    });

    // Restore saved line spacing once the first page is rendered (the content
    // document must exist before we can inject the line-height stylesheet).
    reader.rendition.on("rendered", function onRendered() {
        const savedLineSpacing = localStorage.getItem("calibre.reader.lineSpacing");
        if (savedLineSpacing && window.applyLineSpacing) {
            const parsed = parseFloat(savedLineSpacing);
            if (!isNaN(parsed)) {
                window.applyLineSpacing(parsed);
            }
        }
    });
})();
