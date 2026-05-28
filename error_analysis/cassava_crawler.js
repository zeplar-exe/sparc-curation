// ==UserScript==
// @name         Nginx Recursive Directory Crawler
// @namespace    http://tampermonkey.net/
// @version      1.0
// @description  Crawls nginx directory listings recursively
// @author       You
// @match        https://cassava.ucsd.edu/sparc/datasets/
// @grant        GM_xmlhttpRequest
// @grant        GM_download
// @connect      *
// ==/UserScript==

(function() {
    'use strict';

    let files = new Set();
    let pendingDirs = [];
    let visitedDirs = new Set();

    function crawl(url) {
        if (visitedDirs.has(url)) return;
        visitedDirs.add(url);
        console.log("Crawling: " + url);

        GM_xmlhttpRequest({
            method: "GET",
            url: url,
            onload: function(response) {
                let parser = new DOMParser();
                let doc = parser.parseFromString(response.responseText, "text/html");
                let links = doc.querySelectorAll('a');

                links.forEach(link => {
                    let href = link.getAttribute('href');
                    if (href === '../') return;

                    let absoluteUrl = new URL(href, url).href;

                    if (absoluteUrl.endsWith('/')) {
                        pendingDirs.push(absoluteUrl);
                    } else {
                        files.add(absoluteUrl);
                    }
                });

                if (pendingDirs.length > 0) {
                    crawl(pendingDirs.pop());
                } else {
                    console.log("Crawl complete. Files found:", files);
                    alert("Crawl complete! Found " + files.size + " files. Check console.");
                }
            }
        });
    }

    // Add UI Button
    let btn = document.createElement('button');
    btn.innerHTML = 'Start Recursive Crawl';
    btn.style.position = 'fixed';
    btn.style.top = '10px';
    btn.style.right = '10px';
    btn.style.zIndex = '9999';
    btn.onclick = () => {
        files.clear();
        visitedDirs.clear();
        pendingDirs = [window.location.href];
        crawl(pendingDirs.pop());
    };
    document.body.appendChild(btn);

})();
