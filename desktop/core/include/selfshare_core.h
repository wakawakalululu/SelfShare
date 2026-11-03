#ifndef SELFSHARE_CORE_H
#define SELFSHARE_CORE_H

#ifdef _WIN32
#define SS_EXPORT __declspec(dllexport)
#else
#define SS_EXPORT __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* 所有返回值都是 UTF-8 JSON；调用方必须用 ss_free 释放。 */
SS_EXPORT void ss_free(char *ptr);
SS_EXPORT char *ss_init(void);
SS_EXPORT char *ss_version(void);
SS_EXPORT char *ss_mount(const char *request_json);
SS_EXPORT char *ss_pair(const char *request_json);
SS_EXPORT char *ss_probe(const char *url_utf8);
SS_EXPORT char *ss_unmount(const char *folder_utf8);
SS_EXPORT char *ss_mount_info(const char *folder_utf8);
SS_EXPORT char *ss_find_mount(const char *path_utf8);
SS_EXPORT char *ss_sync(const char *folder_utf8, const char *options_json);
SS_EXPORT char *ss_plan(const char *folder_utf8);
SS_EXPORT char *ss_progress(void);
SS_EXPORT char *ss_watch_start(const char *request_json);
SS_EXPORT char *ss_watch_stop(void);
SS_EXPORT char *ss_watch_status(void);
SS_EXPORT char *ss_history(const char *folder_utf8, const char *path_utf8, int limit);
SS_EXPORT char *ss_restore(const char *request_json);
SS_EXPORT char *ss_remote_stat(const char *folder_utf8);
SS_EXPORT char *ss_shutdown(void);

#ifdef __cplusplus
}
#endif
#endif
